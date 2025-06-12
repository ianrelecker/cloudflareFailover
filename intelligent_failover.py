#!/usr/bin/env python3
import requests
import sys
import logging
import json
import os
import time
import signal
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass, asdict

# Azure monitoring imports (optional)
try:
    from applicationinsights import TelemetryClient
    from opencensus.ext.azure.log_exporter import AzureLogHandler
    AZURE_MONITORING_AVAILABLE = True
except ImportError:
    AZURE_MONITORING_AVAILABLE = False

# Removed Azure Key Vault imports for simplified authentication

@dataclass
class HealthCheck:
    timestamp: datetime
    success: bool
    latency_ms: Optional[float]
    error: Optional[str]

@dataclass
class MonitorState:
    current_ip: str
    is_failed_over: bool
    consecutive_failures: int
    consecutive_successes: int
    last_failover: Optional[datetime]
    last_restore: Optional[datetime]
    health_history: List[HealthCheck]

class IntelligentCloudflareFailover:
    def __init__(self, state_file=None):
        # Azure App Service friendly state file location
        if state_file is None:
            if os.getenv('WEBSITE_SITE_NAME'):  # Running in Azure App Service
                self.state_file = "/tmp/failover_state.json"
            else:
                self.state_file = "failover_state.json"
        else:
            self.state_file = state_file
        self.config = self.load_config()
        self.state = self.load_state()
        self.setup_logging()
        
        # Health check rules per your specs
        self.check_interval = 30  # seconds
        self.latency_threshold_ms = 100
        self.failure_threshold = 2  # consecutive failures before failover
        self.stability_period = 600  # 10 minutes in seconds
        self.success_threshold = self.stability_period // self.check_interval  # ~20 checks
        
        self.running = False
        
        # Cloudflare API headers
        self.headers = {
            "Authorization": f"Bearer {self.config['cf_api_token']}",
            "Content-Type": "application/json"
        }
        
        # Intelligent startup - check and prefer primary if healthy
        # Setup Azure monitoring
        self.setup_azure_monitoring()
        
        # Try intelligent startup, but don't fail if it doesn't work
        try:
            self.intelligent_startup()
        except Exception as e:
            self.logger.warning(f"Intelligent startup failed (continuing anyway): {e}")
            # Reset state to known values if startup failed
            self.state.consecutive_failures = 0
            self.state.consecutive_successes = 0
    
    def setup_logging(self):
        # Azure App Service friendly logging
        log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
        log_file = self.config.get('log_file', '/tmp/intelligent_failover.log')
        
        handlers = [logging.StreamHandler(sys.stdout)]
        
        # Only add file handler if not in Azure App Service (stdout is preferred)
        if not os.getenv('WEBSITE_SITE_NAME'):  # Azure App Service environment variable
            try:
                handlers.append(logging.FileHandler(log_file))
            except PermissionError:
                # Fallback if file logging fails
                pass
        
        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format='%(asctime)s - %(levelname)s - %(message)s [%(filename)s:%(lineno)d]',
            handlers=handlers
        )
        self.logger = logging.getLogger(__name__)
        
        if os.getenv('WEBSITE_SITE_NAME'):
            self.logger.info(f"Running in Azure App Service: {os.getenv('WEBSITE_SITE_NAME')}")
    
    def setup_azure_monitoring(self):
        """Setup Azure Application Insights monitoring"""
        self.telemetry_client = None
        
        if not AZURE_MONITORING_AVAILABLE:
            self.logger.info("Azure monitoring libraries not available - metrics disabled")
            return
            
        # Try to get Application Insights connection string
        app_insights_key = os.getenv('APPLICATIONINSIGHTS_CONNECTION_STRING') or os.getenv('APPINSIGHTS_INSTRUMENTATIONKEY')
        
        if app_insights_key:
            try:
                if app_insights_key.startswith('InstrumentationKey='):
                    # Use connection string format
                    self.telemetry_client = TelemetryClient(app_insights_key)
                else:
                    # Use instrumentation key format  
                    self.telemetry_client = TelemetryClient(app_insights_key)
                self.logger.info("Azure Application Insights monitoring enabled")
            except Exception as e:
                self.logger.warning(f"Failed to setup Azure monitoring: {e}")
        else:
            self.logger.info("No Application Insights key found - metrics disabled")
    
    def send_azure_metric(self, metric_name: str, value: float, properties: dict = None):
        """Send custom metric to Azure Application Insights"""
        if not self.telemetry_client:
            return
            
        try:
            self.telemetry_client.track_metric(metric_name, value, properties=properties)
            self.telemetry_client.flush()
        except Exception as e:
            self.logger.warning(f"Failed to send Azure metric {metric_name}: {e}")
    
    def send_azure_event(self, event_name: str, properties: dict = None, measurements: dict = None):
        """Send custom event to Azure Application Insights"""
        if not self.telemetry_client:
            return
            
        try:
            self.telemetry_client.track_event(event_name, properties=properties, measurements=measurements)
            self.telemetry_client.flush()
        except Exception as e:
            self.logger.warning(f"Failed to send Azure event {event_name}: {e}")
    
    def intelligent_startup(self):
        """Intelligent startup: check current state and prefer primary when healthy"""
        try:
            # Get current DNS record
            record_id, current_dns_ip = self.get_dns_record()
            if not record_id:
                self.logger.warning("Could not get DNS record during startup")
                return
            
            self.logger.info(f"Startup: DNS currently points to {current_dns_ip}")
            
            # Test both servers
            primary_health = self.ping_with_latency(self.config['primary_ip'])
            backup_health = self.ping_with_latency(self.config['backup_ip'])
            
            self.logger.info(f"Primary server health: Success={primary_health.success}, Latency={primary_health.latency_ms}ms")
            self.logger.info(f"Backup server health: Success={backup_health.success}, Latency={backup_health.latency_ms}ms")
            
            # Determine best server
            primary_healthy = primary_health.success and (not primary_health.latency_ms or primary_health.latency_ms <= self.latency_threshold_ms)
            backup_healthy = backup_health.success and (not backup_health.latency_ms or backup_health.latency_ms <= self.latency_threshold_ms)
            
            target_ip = None
            reason = ""
            
            if primary_healthy:
                # Primary is healthy - prefer it
                target_ip = self.config['primary_ip']
                reason = "Primary server is healthy (preferred)"
            elif backup_healthy:
                # Primary unhealthy but backup is healthy
                target_ip = self.config['backup_ip'] 
                reason = "Primary unhealthy, using backup"
            else:
                # Both unhealthy - leave current setting
                self.logger.warning("Both servers appear unhealthy during startup - keeping current DNS")
                return
            
            # Update DNS if needed
            if current_dns_ip != target_ip:
                self.logger.info(f"Startup: Switching DNS from {current_dns_ip} to {target_ip} - {reason}")
                if self.update_dns_record(record_id, target_ip):
                    # Update state
                    self.state.current_ip = target_ip
                    self.state.is_failed_over = (target_ip == self.config['backup_ip'])
                    self.state.consecutive_failures = 0
                    self.state.consecutive_successes = 0
                    if target_ip == self.config['primary_ip']:
                        self.state.last_restore = datetime.now()
                    else:
                        self.state.last_failover = datetime.now()
                    self.save_state()
                    self.logger.info(f"Startup: Successfully updated DNS to {target_ip}")
                    
                    # Send Azure metrics/events
                    self.send_azure_event("DNS_STARTUP_CHANGE", {
                        "from_ip": current_dns_ip,
                        "to_ip": target_ip,
                        "reason": reason,
                        "domain": self.config['domain']
                    })
                else:
                    self.logger.error(f"Startup: Failed to update DNS to {target_ip}")
                    self.send_azure_event("DNS_STARTUP_FAILED", {
                        "target_ip": target_ip,
                        "reason": reason,
                        "domain": self.config['domain']
                    })
            else:
                self.logger.info(f"Startup: DNS already correctly set to {target_ip} - {reason}")
                # Update state to match reality
                self.state.current_ip = current_dns_ip
                self.state.is_failed_over = (current_dns_ip == self.config['backup_ip'])
                
        except Exception as e:
            self.logger.error(f"Error during intelligent startup: {e}")
    
    def load_config(self) -> dict:
        """Load configuration from environment variables or hardcoded values"""
        config = {
            # Authentication - use environment variables (ideal for Azure App Service)
            "cf_api_token": os.getenv("CF_API_TOKEN", "your_cloudflare_api_token_here"),
            "cf_zone_id": os.getenv("CF_ZONE_ID", "your_cloudflare_zone_id_here"),
            
            # Domain configuration - hardcoded for simplicity
            "domain": "signedby.tech",  # Replace with your actual domain
            "primary_ip": "172.171.99.178",  # Azure VM primary IP from bicep
            "backup_ip": "172.171.100.13",   # Azure VM backup IP from bicep
            
            # Other settings
            "record_type": os.getenv("RECORD_TYPE", "A"),
            "ttl": int(os.getenv("TTL", "120")),
            "log_file": os.getenv("LOG_FILE", "/tmp/intelligent_failover.log")
        }
        
        # Validate required fields
        required = ["cf_api_token", "cf_zone_id"]
        missing = [field for field in required if not config.get(field) or config.get(field).startswith("your_")]
        
        if missing:
            print("Please configure the following:")
            print("1. Set CF_API_TOKEN environment variable with your Cloudflare API token")
            print("2. Set CF_ZONE_ID environment variable with your Cloudflare Zone ID")
            print("3. Update the domain name in the script (line 96)")
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")
            
        return config
    
    
    def load_state(self) -> MonitorState:
        """Load monitoring state from file"""
        if not os.path.exists(self.state_file):
            return MonitorState(
                current_ip="",
                is_failed_over=False,
                consecutive_failures=0,
                consecutive_successes=0,
                last_failover=None,
                last_restore=None,
                health_history=[]
            )
        
        try:
            with open(self.state_file, 'r') as f:
                data = json.load(f)
            
            # Convert datetime strings back to datetime objects
            if data.get('last_failover'):
                data['last_failover'] = datetime.fromisoformat(data['last_failover'])
            if data.get('last_restore'):
                data['last_restore'] = datetime.fromisoformat(data['last_restore'])
            
            # Convert health history
            health_history = []
            for h in data.get('health_history', []):
                health_history.append(HealthCheck(
                    timestamp=datetime.fromisoformat(h['timestamp']),
                    success=h['success'],
                    latency_ms=h.get('latency_ms'),
                    error=h.get('error')
                ))
            data['health_history'] = health_history
            
            return MonitorState(**data)
        except Exception as e:
            self.logger.error(f"Failed to load state: {e}")
            return MonitorState(
                current_ip="",
                is_failed_over=False,
                consecutive_failures=0,
                consecutive_successes=0,
                last_failover=None,
                last_restore=None,
                health_history=[]
            )
    
    def save_state(self):
        """Save monitoring state to file"""
        try:
            data = asdict(self.state)
            
            # Convert datetime objects to strings
            if data['last_failover']:
                data['last_failover'] = data['last_failover'].isoformat()
            if data['last_restore']:
                data['last_restore'] = data['last_restore'].isoformat()
            
            # Convert health history
            health_history = []
            for h in data['health_history']:
                h_dict = dict(h)
                h_dict['timestamp'] = h_dict['timestamp'].isoformat()
                health_history.append(h_dict)
            data['health_history'] = health_history
            
            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}")
    
    def ping_with_latency(self, ip: str) -> HealthCheck:
        """Health check using HTTP request (Azure App Service compatible)"""
        try:
            start_time = time.time()
            
            # Try HTTP first, then HTTPS
            for protocol in ['http', 'https']:
                try:
                    url = f"{protocol}://{ip}"
                    response = requests.get(url, timeout=5, allow_redirects=False)
                    end_time = time.time()
                    latency_ms = (end_time - start_time) * 1000
                    
                    # Consider 2xx, 3xx, 4xx as "server responding" (healthy)
                    # Only 5xx or connection errors are unhealthy
                    if response.status_code < 500:
                        return HealthCheck(
                            timestamp=datetime.now(),
                            success=True,
                            latency_ms=latency_ms,
                            error=None
                        )
                    else:
                        return HealthCheck(
                            timestamp=datetime.now(),
                            success=False,
                            latency_ms=latency_ms,
                            error=f"HTTP {response.status_code}"
                        )
                        
                except requests.exceptions.ConnectionError:
                    # Try next protocol
                    continue
                except requests.exceptions.Timeout:
                    end_time = time.time()
                    return HealthCheck(
                        timestamp=datetime.now(),
                        success=False,
                        latency_ms=(end_time - start_time) * 1000,
                        error="HTTP timeout"
                    )
                except Exception as e:
                    # Try next protocol
                    continue
            
            # If both HTTP and HTTPS failed
            end_time = time.time()
            return HealthCheck(
                timestamp=datetime.now(),
                success=False,
                latency_ms=(end_time - start_time) * 1000,
                error="HTTP connection failed"
            )
            
        except Exception as e:
            return HealthCheck(
                timestamp=datetime.now(),
                success=False,
                latency_ms=None,
                error=str(e)
            )
    
    def get_dns_record(self) -> tuple[Optional[str], Optional[str]]:
        """Get current DNS record ID and content"""
        url = f"https://api.cloudflare.com/client/v4/zones/{self.config['cf_zone_id']}/dns_records"
        params = {"name": self.config['domain'], "type": self.config['record_type']}
        
        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data["success"] and data["result"]:
                return data["result"][0]["id"], data["result"][0]["content"]
            else:
                self.logger.error(f"Failed to get DNS record: {data.get('errors')}")
                return None, None
        except Exception as e:
            self.logger.error(f"Error getting DNS record: {e}")
            return None, None
    
    def update_dns_record(self, record_id: str, new_ip: str) -> bool:
        """Update DNS record with new IP"""
        url = f"https://api.cloudflare.com/client/v4/zones/{self.config['cf_zone_id']}/dns_records/{record_id}"
        data = {
            "type": self.config['record_type'],
            "name": self.config['domain'],
            "content": new_ip,
            "ttl": self.config['ttl'],
            "proxied": False
        }
        
        try:
            response = requests.put(url, headers=self.headers, json=data)
            response.raise_for_status()
            result = response.json()
            return result["success"]
        except Exception as e:
            self.logger.error(f"Failed to update DNS record: {e}")
            return False
    
    def should_failover(self, health_check: HealthCheck) -> bool:
        """Determine if we should failover based on health check"""
        if self.state.is_failed_over:
            return False
        
        # Check if health check failed or latency too high
        if not health_check.success:
            return self.state.consecutive_failures >= self.failure_threshold
        
        if health_check.latency_ms and health_check.latency_ms > self.latency_threshold_ms:
            self.logger.warning(f"High latency detected: {health_check.latency_ms}ms")
            return self.state.consecutive_failures >= self.failure_threshold
        
        return False
    
    def should_restore(self, health_check: HealthCheck) -> bool:
        """Determine if we should restore based on 10-minute stability"""
        if not self.state.is_failed_over:
            return False
        
        # Must be successful and low latency
        if not health_check.success:
            return False
        
        if health_check.latency_ms and health_check.latency_ms > self.latency_threshold_ms:
            return False
        
        # Check if we have enough consecutive successes for stability period
        if self.state.consecutive_successes >= self.success_threshold:
            self.logger.info(f"Primary stable for {self.stability_period}s, ready to restore")
            return True
        
        return False
    
    def update_state(self, health_check: HealthCheck):
        """Update monitoring state based on health check result"""
        # Add to health history (keep last 100 results)
        self.state.health_history.append(health_check)
        if len(self.state.health_history) > 100:
            self.state.health_history.pop(0)
        
        # Update consecutive counters
        is_healthy = health_check.success and (
            not health_check.latency_ms or 
            health_check.latency_ms <= self.latency_threshold_ms
        )
        
        if is_healthy:
            self.state.consecutive_failures = 0
            self.state.consecutive_successes += 1
        else:
            self.state.consecutive_failures += 1
            self.state.consecutive_successes = 0
    
    def process_health_check(self):
        """Perform health check and take action if needed"""
        # Get current DNS record
        record_id, current_dns_ip = self.get_dns_record()
        if not record_id:
            self.logger.error("Could not get DNS record")
            return False
        
        self.state.current_ip = current_dns_ip
        
        # Perform health check on primary IP
        health_check = self.ping_with_latency(self.config['primary_ip'])
        
        # Log current status with enhanced formatting
        latency_str = f"{health_check.latency_ms:.1f}ms" if health_check.latency_ms else "None"
        success_icon = "✅" if health_check.success else "❌"
        latency_icon = "🚀" if health_check.latency_ms and health_check.latency_ms < 50 else "⚡" if health_check.latency_ms and health_check.latency_ms < 100 else "⏳"
        
        status_msg = (f"{success_icon} Health Check → Target: {self.config['primary_ip']} | "
                     f"Status: {'PASS' if health_check.success else 'FAIL'} | "
                     f"Latency: {latency_icon} {latency_str} | "
                     f"Failures: {self.state.consecutive_failures}/{self.failure_threshold} | "
                     f"Successes: {self.state.consecutive_successes}/{self.success_threshold}")
        
        if self.state.is_failed_over:
            status_msg += " | 🔄 [FAILED OVER TO BACKUP]"
        else:
            status_msg += " | 🏠 [PRIMARY ACTIVE]"
        
        if health_check.error:
            status_msg += f" | Error: {health_check.error}"
        
        self.logger.info(status_msg)
        
        # Send health check metrics to Azure
        self.send_azure_metric("cloudflare_failover.health_check_success", 1.0 if health_check.success else 0.0, {
            "domain": self.config['domain'],
            "target_ip": self.config['primary_ip'],
            "is_failed_over": str(self.state.is_failed_over)
        })
        
        if health_check.latency_ms:
            self.send_azure_metric("cloudflare_failover.latency_ms", health_check.latency_ms, {
                "domain": self.config['domain'],
                "target_ip": self.config['primary_ip']
            })
        
        self.send_azure_metric("cloudflare_failover.consecutive_failures", float(self.state.consecutive_failures), {
            "domain": self.config['domain']
        })
        
        # Update state
        self.update_state(health_check)
        
        # Determine action
        action_taken = False
        
        if self.should_failover(health_check):
            self.logger.warning("🚨" * 20)
            self.logger.warning(f"🚨 INITIATING FAILOVER: {self.config['primary_ip']} → {self.config['backup_ip']}")
            self.logger.warning(f"🚨 Trigger: {self.state.consecutive_failures} consecutive failures")
            self.logger.warning("🚨" * 20)
            if self.update_dns_record(record_id, self.config['backup_ip']):
                self.state.is_failed_over = True
                self.state.last_failover = datetime.now()
                self.state.current_ip = self.config['backup_ip']
                self.state.consecutive_failures = 0  # Reset after successful failover
                action_taken = True
                self.logger.warning("✅ FAILOVER COMPLETE: DNS now points to backup server")
                self.logger.warning(f"📍 Domain {self.config['domain']} → {self.config['backup_ip']}")
                
                # Send failover event to Azure
                self.send_azure_event("DNS_FAILOVER", {
                    "domain": self.config['domain'],
                    "from_ip": self.config['primary_ip'],
                    "to_ip": self.config['backup_ip'],
                    "trigger": "health_check_failure"
                }, {
                    "consecutive_failures": float(self.state.consecutive_failures)
                })
                
                # Send critical alert metric
                self.send_azure_metric("cloudflare_failover.failover_event", 1.0, {
                    "domain": self.config['domain'],
                    "event_type": "failover"
                })
            else:
                self.logger.error("Failed to update DNS record during failover")
                self.send_azure_event("DNS_FAILOVER_FAILED", {
                    "domain": self.config['domain'],
                    "target_ip": self.config['backup_ip']
                })
        
        elif self.should_restore(health_check):
            self.logger.info("🔄" * 20)
            self.logger.info(f"🔄 INITIATING RESTORE: {self.config['backup_ip']} → {self.config['primary_ip']}")
            self.logger.info(f"🔄 Trigger: Primary stable for {self.stability_period}s ({self.state.consecutive_successes} successful checks)")
            self.logger.info("🔄" * 20)
            if self.update_dns_record(record_id, self.config['primary_ip']):
                self.state.is_failed_over = False
                self.state.last_restore = datetime.now()
                self.state.current_ip = self.config['primary_ip']
                self.state.consecutive_successes = 0  # Reset after restore
                action_taken = True
                self.logger.info("✅ RESTORE COMPLETE: DNS now points to primary server")
                self.logger.info(f"📍 Domain {self.config['domain']} → {self.config['primary_ip']}")
                
                # Send restore event to Azure
                self.send_azure_event("DNS_RESTORE", {
                    "domain": self.config['domain'],
                    "from_ip": self.config['backup_ip'],
                    "to_ip": self.config['primary_ip'],
                    "trigger": "primary_healthy_stable"
                }, {
                    "stability_period_seconds": float(self.stability_period),
                    "consecutive_successes": float(self.state.consecutive_successes)
                })
                
                # Send restore metric
                self.send_azure_metric("cloudflare_failover.restore_event", 1.0, {
                    "domain": self.config['domain'],
                    "event_type": "restore"
                })
            else:
                self.logger.error("Failed to update DNS record during restore")
                self.send_azure_event("DNS_RESTORE_FAILED", {
                    "domain": self.config['domain'],
                    "target_ip": self.config['primary_ip']
                })
        
        # Save state if action was taken
        if action_taken:
            self.save_state()
        
        return True
    
    def monitor_loop(self):
        """Main monitoring loop"""
        self.logger.info("=" * 80)
        self.logger.info("🚀 STARTING CLOUDFLARE DNS FAILOVER MONITORING")
        self.logger.info("=" * 80)
        self.logger.info(f"📍 Domain: {self.config['domain']}")
        self.logger.info(f"🔧 Primary Server: {self.config['primary_ip']}")
        self.logger.info(f"🔧 Backup Server: {self.config['backup_ip']}")
        self.logger.info(f"⏱️  Check Interval: {self.check_interval} seconds")
        self.logger.info(f"🚨 Latency Threshold: {self.latency_threshold_ms}ms")
        self.logger.info(f"💥 Failure Threshold: {self.failure_threshold} consecutive failures")
        self.logger.info(f"🔄 Stability Period: {self.stability_period} seconds (~{self.success_threshold} checks)")
        self.logger.info("=" * 80)
        
        self.running = True
        cycle_count = 0
        
        # Set up signal handlers for graceful shutdown
        def signal_handler(_signum, _frame):
            self.logger.info("Received shutdown signal")
            self.running = False
            self.save_state()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        while self.running:
            cycle_count += 1
            start_time = time.time()
            
            # Log cycle header every 10 cycles (5 minutes) or on first cycle
            if cycle_count == 1 or cycle_count % 10 == 0:
                self.logger.info("-" * 60)
                self.logger.info(f"🔍 MONITORING CYCLE #{cycle_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                status = self.get_status()
                self.logger.info(f"📊 Current Status: DNS → {status['current_ip']} {'[FAILED OVER]' if status['is_failed_over'] else '[PRIMARY]'}")
                self.logger.info(f"📈 Health History: {status['health_checks_total']} total checks")
                if cycle_count > 1:
                    self.logger.info(f"⏰ Next detailed summary in {10 - (cycle_count % 10)} cycles")
                self.logger.info("-" * 60)
            
            try:
                self.process_health_check()
            except Exception as e:
                self.logger.error(f"❌ Error in health check cycle #{cycle_count}: {e}")
            
            # Save state periodically
            self.save_state()
            
            # Sleep for remaining time in interval
            elapsed = time.time() - start_time
            sleep_time = max(0, self.check_interval - elapsed)
            
            # Log next check countdown for first few cycles
            if cycle_count <= 5:
                self.logger.info(f"⏳ Cycle #{cycle_count} complete ({elapsed:.1f}s). Next check in {sleep_time:.1f}s...")
            
            if self.running:  # Only sleep if still running
                time.sleep(sleep_time)
    
    def get_status(self) -> dict:
        """Get current status"""
        # Get current DNS record
        record_id, current_dns_ip = self.get_dns_record()
        
        status = {
            "domain": self.config['domain'],
            "current_ip": current_dns_ip or "unknown",
            "primary_ip": self.config['primary_ip'],
            "backup_ip": self.config['backup_ip'],
            "is_failed_over": self.state.is_failed_over,
            "consecutive_failures": self.state.consecutive_failures,
            "consecutive_successes": self.state.consecutive_successes,
            "last_failover": self.state.last_failover.isoformat() if self.state.last_failover else None,
            "last_restore": self.state.last_restore.isoformat() if self.state.last_restore else None,
            "health_checks_total": len(self.state.health_history)
        }
        
        if self.state.health_history:
            latest = self.state.health_history[-1]
            status.update({
                "last_check": latest.timestamp.isoformat(),
                "last_success": latest.success,
                "last_latency_ms": latest.latency_ms,
                "last_error": latest.error
            })
        
        return status
    
    def manual_failover(self) -> bool:
        """Manually trigger failover"""
        if self.state.is_failed_over:
            self.logger.warning("Already failed over")
            return False
        
        record_id, current_ip = self.get_dns_record()
        if not record_id:
            return False
        
        if self.update_dns_record(record_id, self.config['backup_ip']):
            self.state.is_failed_over = True
            self.state.last_failover = datetime.now()
            self.state.current_ip = self.config['backup_ip']
            self.save_state()
            self.logger.info("Manual failover completed")
            return True
        
        return False
    
    def manual_restore(self) -> bool:
        """Manually trigger restore"""
        if not self.state.is_failed_over:
            self.logger.warning("Not currently failed over")
            return False
        
        record_id, current_ip = self.get_dns_record()
        if not record_id:
            return False
        
        if self.update_dns_record(record_id, self.config['primary_ip']):
            self.state.is_failed_over = False
            self.state.last_restore = datetime.now()
            self.state.current_ip = self.config['primary_ip']
            self.state.consecutive_successes = 0  # Reset stability counter
            self.save_state()
            self.logger.info("Manual restore completed")
            return True
        
        return False

def main():
    if len(sys.argv) < 2:
        print("Usage: intelligent_failover.py [command]")
        print("Commands:")
        print("  monitor   - Start continuous monitoring")
        print("  status    - Show current status")
        print("  failover  - Manual failover to backup")
        print("  restore   - Manual restore to primary")
        print("  check     - Single health check")
        print("")
        print("Configuration:")
        print("  Set environment variables: CF_API_TOKEN, CF_ZONE_ID")
        print("  Or edit domain/IP values directly in the script")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    try:
        failover = IntelligentCloudflareFailover()
        
        if command == "monitor":
            failover.monitor_loop()
        elif command == "status":
            status = failover.get_status()
            print(json.dumps(status, indent=2))
        elif command == "failover":
            success = failover.manual_failover()
            sys.exit(0 if success else 1)
        elif command == "restore":
            success = failover.manual_restore()
            sys.exit(0 if success else 1)
        elif command == "check":
            success = failover.process_health_check()
            sys.exit(0 if success else 1)
        else:
            print(f"Unknown command: {command}")
            sys.exit(1)
    
    except KeyboardInterrupt:
        print("\nMonitoring stopped")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Script failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()