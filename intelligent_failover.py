#!/usr/bin/env python3
import requests
import sys
import logging
import json
import os
import time
import subprocess
import signal
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict

# Azure Key Vault imports
try:
    from azure.keyvault.secrets import SecretClient
    from azure.identity import DefaultAzureCredential, ClientSecretCredential
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False

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
    def __init__(self, state_file="failover_state.json"):
        self.state_file = state_file
        self.config = self.load_config()
        self.state = self.load_state()
        self.setup_logging()
        self.key_vault_client = None
        self._init_azure_key_vault()
        
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
    
    def setup_logging(self):
        log_file = self.config.get('log_file', '/var/log/intelligent_failover.log')
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler(log_file)
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def _init_azure_key_vault(self):
        """Initialize Azure Key Vault client if configured"""
        vault_url = self.config.get('azure_key_vault_url') or os.getenv('AZURE_KEY_VAULT_URL')
        
        if not vault_url or not AZURE_AVAILABLE:
            if vault_url and not AZURE_AVAILABLE:
                self.logger.warning("Azure Key Vault URL provided but azure-keyvault-secrets not installed")
            return
        
        try:
            # Try different authentication methods
            tenant_id = self.config.get('azure_tenant_id') or os.getenv('AZURE_TENANT_ID')
            client_id = self.config.get('azure_client_id') or os.getenv('AZURE_CLIENT_ID')
            client_secret = self.config.get('azure_client_secret') or os.getenv('AZURE_CLIENT_SECRET')
            
            if tenant_id and client_id and client_secret:
                # Service principal authentication
                credential = ClientSecretCredential(
                    tenant_id=tenant_id,
                    client_id=client_id,
                    client_secret=client_secret
                )
                self.logger.info("Using Azure service principal authentication")
            else:
                # Default credential chain (managed identity, Azure CLI, etc.)
                credential = DefaultAzureCredential()
                self.logger.info("Using Azure default credential chain")
            
            self.key_vault_client = SecretClient(vault_url=vault_url, credential=credential)
            self.logger.info(f"Azure Key Vault client initialized for {vault_url}")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Azure Key Vault: {e}")
            self.key_vault_client = None
    
    def _get_secret_from_vault(self, secret_name: str) -> Optional[str]:
        """Retrieve secret from Azure Key Vault"""
        if not self.key_vault_client:
            return None
        
        try:
            secret = self.key_vault_client.get_secret(secret_name)
            return secret.value
        except Exception as e:
            self.logger.error(f"Failed to retrieve secret '{secret_name}' from Key Vault: {e}")
            return None
    
    def load_config(self) -> dict:
        """Load configuration from file or environment variables"""
        # Hardcoded values
        config = {
            "cf_api_token": os.getenv("CF_API_TOKEN"),
            "cf_zone_id": os.getenv("CF_ZONE_ID"),
            "domain": "example.com",  # Replace with your actual domain
            "primary_ip": "1.2.3.4",  # Replace with your primary server IP
            "backup_ip": "5.6.7.8",   # Replace with your backup server IP
            "record_type": os.getenv("RECORD_TYPE", "A"),
            "ttl": int(os.getenv("TTL", "120")),
            "log_file": os.getenv("LOG_FILE", "/var/log/intelligent_failover.log"),
            # Azure Key Vault configuration
            "azure_key_vault_url": os.getenv("AZURE_KEY_VAULT_URL"),
            "azure_tenant_id": os.getenv("AZURE_TENANT_ID"),
            "azure_client_id": os.getenv("AZURE_CLIENT_ID"),
            "azure_client_secret": os.getenv("AZURE_CLIENT_SECRET"),
            # Key Vault secret names (with defaults)
            "kv_cf_api_token_name": os.getenv("KV_CF_API_TOKEN_NAME", "cloudflare-api-token"),
            "kv_cf_zone_id_name": os.getenv("KV_CF_ZONE_ID_NAME", "cloudflare-zone-id")
        }
        
        # Initialize Key Vault client with current config
        self._init_azure_key_vault_from_config(config)
        
        # Override sensitive values from Azure Key Vault if available
        if self.key_vault_client:
            vault_token = self._get_secret_from_vault(config.get('kv_cf_api_token_name', 'cloudflare-api-token'))
            if vault_token:
                config['cf_api_token'] = vault_token
                self.logger.info("Retrieved Cloudflare API token from Azure Key Vault")
            
            vault_zone_id = self._get_secret_from_vault(config.get('kv_cf_zone_id_name', 'cloudflare-zone-id'))
            if vault_zone_id:
                config['cf_zone_id'] = vault_zone_id
                self.logger.info("Retrieved Cloudflare Zone ID from Azure Key Vault")
        
        # Validate required fields
        required = ["cf_api_token", "cf_zone_id"]
        missing = [field for field in required if not config.get(field)]
        
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")
            
        return config
    
    def _init_azure_key_vault_from_config(self, config: Dict[str, Any]):
        """Initialize Azure Key Vault client from config (used during config loading)"""
        vault_url = config.get('azure_key_vault_url')
        
        if not vault_url or not AZURE_AVAILABLE:
            return
        
        try:
            tenant_id = config.get('azure_tenant_id')
            client_id = config.get('azure_client_id')
            client_secret = config.get('azure_client_secret')
            
            if tenant_id and client_id and client_secret:
                credential = ClientSecretCredential(
                    tenant_id=tenant_id,
                    client_id=client_id,
                    client_secret=client_secret
                )
            else:
                credential = DefaultAzureCredential()
            
            self.key_vault_client = SecretClient(vault_url=vault_url, credential=credential)
            
        except Exception as e:
            self.logger = logging.getLogger(__name__)  # Ensure logger exists
            self.logger.error(f"Failed to initialize Azure Key Vault during config load: {e}")
            self.key_vault_client = None
    
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
        """Ping an IP and measure latency"""
        try:
            start_time = time.time()
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "5", ip],
                capture_output=True,
                timeout=10,
                text=True
            )
            end_time = time.time()
            
            if result.returncode == 0:
                # Extract latency from ping output
                output = result.stdout
                if "time=" in output:
                    try:
                        latency_str = output.split("time=")[1].split()[0]
                        latency_ms = float(latency_str)
                    except:
                        latency_ms = (end_time - start_time) * 1000
                else:
                    latency_ms = (end_time - start_time) * 1000
                
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
                    latency_ms=None,
                    error=f"Ping failed: {result.stderr.strip()}"
                )
        
        except subprocess.TimeoutExpired:
            return HealthCheck(
                timestamp=datetime.now(),
                success=False,
                latency_ms=None,
                error="Ping timeout"
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
        
        # Log current status
        status_msg = (f"Health check - Success: {health_check.success}, "
                     f"Latency: {health_check.latency_ms}ms, "
                     f"Consecutive failures: {self.state.consecutive_failures}, "
                     f"Consecutive successes: {self.state.consecutive_successes}")
        
        if self.state.is_failed_over:
            status_msg += " [FAILED OVER]"
        
        self.logger.info(status_msg)
        
        # Update state
        self.update_state(health_check)
        
        # Determine action
        action_taken = False
        
        if self.should_failover(health_check):
            self.logger.warning(f"Failing over to backup IP {self.config['backup_ip']}")
            if self.update_dns_record(record_id, self.config['backup_ip']):
                self.state.is_failed_over = True
                self.state.last_failover = datetime.now()
                self.state.current_ip = self.config['backup_ip']
                self.state.consecutive_failures = 0  # Reset after successful failover
                action_taken = True
                self.logger.info("Successfully failed over to backup")
            else:
                self.logger.error("Failed to update DNS record during failover")
        
        elif self.should_restore(health_check):
            self.logger.info(f"Restoring to primary IP {self.config['primary_ip']}")
            if self.update_dns_record(record_id, self.config['primary_ip']):
                self.state.is_failed_over = False
                self.state.last_restore = datetime.now()
                self.state.current_ip = self.config['primary_ip']
                self.state.consecutive_successes = 0  # Reset after restore
                action_taken = True
                self.logger.info("Successfully restored to primary")
            else:
                self.logger.error("Failed to update DNS record during restore")
        
        # Save state if action was taken
        if action_taken:
            self.save_state()
        
        return True
    
    def monitor_loop(self):
        """Main monitoring loop"""
        self.logger.info("Starting intelligent DNS failover monitoring")
        self.logger.info(f"Rules: Ping every {self.check_interval}s, "
                        f"Latency threshold: {self.latency_threshold_ms}ms, "
                        f"Failure threshold: {self.failure_threshold} consecutive, "
                        f"Stability period: {self.stability_period}s")
        
        self.running = True
        
        # Set up signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            self.logger.info("Received shutdown signal")
            self.running = False
            self.save_state()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        while self.running:
            start_time = time.time()
            
            try:
                self.process_health_check()
            except Exception as e:
                self.logger.error(f"Error in health check: {e}")
            
            # Save state periodically
            self.save_state()
            
            # Sleep for remaining time in interval
            elapsed = time.time() - start_time
            sleep_time = max(0, self.check_interval - elapsed)
            
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
        print("  Set AZURE_KEY_VAULT_URL for Azure Key Vault integration")
        print("  Or use environment variables: CF_API_TOKEN, CF_ZONE_ID, etc.")
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