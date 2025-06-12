#!/usr/bin/env python3
"""
Azure App Service startup script for Cloudflare DNS Failover
This script automatically starts the intelligent failover monitor
"""

import os
import sys
import time
import traceback

def main():
    """Main entry point for Azure App Service"""
    print("=" * 60)
    print("🚀 Cloudflare DNS Failover Monitor for Azure App Service")
    print("=" * 60)
    print(f"App Service Name: {os.getenv('WEBSITE_SITE_NAME', 'Local Development')}")
    print(f"Python Version: {sys.version}")
    print(f"Working Directory: {os.getcwd()}")
    print()
    
    # Check environment variables
    print("🔍 Checking configuration...")
    required_vars = ['CF_API_TOKEN', 'CF_ZONE_ID']
    config_status = {}
    
    for var in required_vars:
        value = os.getenv(var)
        if value:
            if value.startswith('your_'):
                config_status[var] = "❌ DEFAULT VALUE (needs configuration)"
            else:
                config_status[var] = f"✅ CONFIGURED ({len(value)} chars)"
        else:
            config_status[var] = "❌ MISSING"
    
    # Display configuration status
    for var, status in config_status.items():
        print(f"  {var}: {status}")
    
    # Check for missing or default values
    missing_vars = [var for var, status in config_status.items() if "❌" in status]
    
    if missing_vars:
        print()
        print("🚫 Configuration Error:")
        print("Please configure the following in Azure App Service:")
        print("Configuration → Application Settings:")
        for var in missing_vars:
            if "DEFAULT VALUE" in config_status[var]:
                print(f"  • {var}: Replace default value with your actual Cloudflare {var.lower().replace('_', ' ')}")
            else:
                print(f"  • {var}: Add your Cloudflare {var.lower().replace('_', ' ')}")
        print()
        print("📖 See azure-app-service.md for complete setup guide")
        sys.exit(1)
    
    print("✅ Configuration validated")
    print()
    
    try:
        print("🔧 Initializing Cloudflare DNS Failover Monitor...")
        # Import here to catch import errors with better context
        from intelligent_failover import IntelligentCloudflareFailover
        
        failover = IntelligentCloudflareFailover()
        print("✅ Monitor initialized successfully")
        print()
        
        # Display current configuration
        status = failover.get_status()
        print(f"📍 Monitoring domain: {status['domain']}")
        print(f"🔧 Primary server: {status['primary_ip']}")
        print(f"🔧 Backup server: {status['backup_ip']}")
        print(f"📊 Current DNS points to: {status['current_ip']}")
        print()
        
        print("🏃 Starting continuous monitoring...")
        print("Monitor will check health every 30 seconds")
        print("Logs will appear below:")
        print("-" * 60)
        
        # Start monitoring loop
        failover.monitor_loop()
        
    except ImportError as e:
        print(f"❌ Import Error: {e}")
        print("Check that all required files are present in the deployment")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n🛑 Monitoring stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"❌ ERROR: Failed to start monitor: {e}")
        print("\n🔍 Full error details:")
        traceback.print_exc()
        sys.exit(1)

def create_simple_app():
    """Create a simple Flask-like app for Azure App Service"""
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import json
    from datetime import datetime
    
    # Global variables for monitoring status
    monitor_instance = None
    monitor_status = {"running": False, "error": None, "started_at": None}
    
    class SimpleHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/':
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                status = "RUNNING" if monitor_status['running'] else "STOPPED"
                error = f" (ERROR: {monitor_status['error']})" if monitor_status['error'] else ""
                self.wfile.write(f"Cloudflare DNS Failover Monitor: {status}{error}\n".encode())
            elif self.path == '/health':
                status_code = 200 if monitor_status['running'] else 503
                self.send_response(status_code)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                health = {
                    "status": "healthy" if monitor_status['running'] else "unhealthy",
                    "timestamp": datetime.now().isoformat(),
                    "monitor_running": monitor_status['running'],
                    "error": monitor_status.get('error')
                }
                self.wfile.write(json.dumps(health).encode())
            else:
                self.send_response(404)
                self.end_headers()
        
        def log_message(self, format, *args):
            pass  # Suppress HTTP logs
    
    def start_monitor_background():
        global monitor_instance, monitor_status
        try:
            print("🔧 Starting DNS monitor in background...")
            monitor_status = {"running": False, "error": None, "started_at": datetime.now()}
            
            from intelligent_failover import IntelligentCloudflareFailover
            monitor_instance = IntelligentCloudflareFailover()
            monitor_status['running'] = True
            monitor_status['error'] = None
            print("✅ DNS Monitor started successfully")
            
            # Start monitoring loop
            monitor_instance.monitor_loop()
            
        except Exception as e:
            error_details = f"{type(e).__name__}: {str(e)}"
            if 'monitor_status' not in locals():
                monitor_status = {"running": False, "error": error_details, "started_at": datetime.now()}
            else:
                monitor_status['running'] = False
                monitor_status['error'] = error_details
            print(f"❌ DNS Monitor failed: {error_details}")
            import traceback
            print("Full error traceback:")
            traceback.print_exc()
    
    # Start monitor in background thread
    monitor_thread = threading.Thread(target=start_monitor_background, daemon=True)
    monitor_thread.start()
    
    # Start simple HTTP server
    port = int(os.getenv('PORT', 8000))
    print(f"🌐 Starting health check server on 0.0.0.0:{port}")
    try:
        server = HTTPServer(('0.0.0.0', port), SimpleHandler)
        print(f"🌐 Health check server started successfully on port {port}")
        server.serve_forever()
    except Exception as e:
        print(f"❌ Failed to start server on port {port}: {e}")
        # Fallback - just run the monitor without web server
        main()

if __name__ == "__main__":
    if os.getenv('WEBSITE_SITE_NAME'):
        # Running on Azure App Service - use web server approach
        print("🔍 Azure App Service detected - starting with web interface...")
        
        # Validate config first
        required_vars = ['CF_API_TOKEN', 'CF_ZONE_ID']
        missing_vars = []
        for var in required_vars:
            value = os.getenv(var)
            if not value or value.startswith('your_'):
                missing_vars.append(var)
        
        if missing_vars:
            print("❌ Missing configuration. Please set these environment variables:")
            for var in missing_vars:
                print(f"  • {var}")
            sys.exit(1)
        
        create_simple_app()
    else:
        # Running locally - use original approach
        main()