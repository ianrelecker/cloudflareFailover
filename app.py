#!/usr/bin/env python3
"""
Azure App Service web interface for Cloudflare DNS Failover
Provides HTTP endpoints for health checks and status monitoring
"""

import os
import sys
import json
import threading
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from intelligent_failover import IntelligentCloudflareFailover

# Global monitor instance
monitor = None
monitor_thread = None
monitor_status = {"running": False, "error": None, "started_at": None}

class StatusHandler(BaseHTTPRequestHandler):
    """HTTP request handler for status endpoints"""
    
    def do_GET(self):
        """Handle GET requests"""
        try:
            if self.path == '/':
                self.send_homepage()
            elif self.path == '/health':
                self.send_health_check()
            elif self.path == '/status':
                self.send_status()
            elif self.path == '/config':
                self.send_config()
            else:
                self.send_404()
        except Exception as e:
            self.send_error_response(f"Server error: {e}")
    
    def send_homepage(self):
        """Send homepage with basic info"""
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Cloudflare DNS Failover Monitor</title>
            <meta http-equiv="refresh" content="30">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .status {{ padding: 10px; border-radius: 5px; margin: 10px 0; }}
                .success {{ background-color: #d4edda; color: #155724; }}
                .error {{ background-color: #f8d7da; color: #721c24; }}
                .info {{ background-color: #d1ecf1; color: #0c5460; }}
            </style>
        </head>
        <body>
            <h1>🚀 Cloudflare DNS Failover Monitor</h1>
            <p><strong>App Service:</strong> {os.getenv('WEBSITE_SITE_NAME', 'Local Development')}</p>
            <p><strong>Last Updated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            
            <div class="status {'success' if monitor_status['running'] else 'error'}">
                <strong>Monitor Status:</strong> {'✅ Running' if monitor_status['running'] else '❌ Stopped'}
            </div>
            
            {f'<div class="status error"><strong>Error:</strong> {monitor_status["error"]}</div>' if monitor_status['error'] else ''}
            
            <h2>📊 Current Status</h2>
            <p><a href="/status">View JSON Status</a> | <a href="/health">Health Check</a> | <a href="/config">Configuration</a></p>
            
            <p><em>This page auto-refreshes every 30 seconds</em></p>
        </body>
        </html>
        """
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode())
    
    def send_health_check(self):
        """Send basic health check response"""
        health = {
            "status": "healthy" if monitor_status['running'] else "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "app_service": os.getenv('WEBSITE_SITE_NAME'),
            "monitor_running": monitor_status['running'],
            "error": monitor_status.get('error')
        }
        
        status_code = 200 if monitor_status['running'] else 503
        self.send_json_response(health, status_code)
    
    def send_status(self):
        """Send detailed status from monitor"""
        try:
            if monitor:
                status = monitor.get_status()
                status['monitor_info'] = monitor_status
            else:
                status = {"error": "Monitor not initialized", "monitor_info": monitor_status}
            
            self.send_json_response(status)
        except Exception as e:
            self.send_error_response(f"Failed to get status: {e}")
    
    def send_config(self):
        """Send configuration info (without sensitive data)"""
        config = {
            "app_service_name": os.getenv('WEBSITE_SITE_NAME'),
            "environment_variables": {
                "CF_API_TOKEN": "✅ Configured" if os.getenv('CF_API_TOKEN') and not os.getenv('CF_API_TOKEN').startswith('your_') else "❌ Missing or default",
                "CF_ZONE_ID": "✅ Configured" if os.getenv('CF_ZONE_ID') and not os.getenv('CF_ZONE_ID').startswith('your_') else "❌ Missing or default",
                "LOG_LEVEL": os.getenv('LOG_LEVEL', 'INFO'),
                "TTL": os.getenv('TTL', '120')
            },
            "python_version": sys.version,
            "working_directory": os.getcwd()
        }
        
        self.send_json_response(config)
    
    def send_json_response(self, data, status_code=200):
        """Send JSON response"""
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, default=str).encode())
    
    def send_error_response(self, message, status_code=500):
        """Send error response"""
        error = {"error": message, "timestamp": datetime.now().isoformat()}
        self.send_json_response(error, status_code)
    
    def send_404(self):
        """Send 404 response"""
        self.send_error_response("Not found", 404)
    
    def log_message(self, format, *args):
        """Override to reduce logging noise"""
        pass

def start_monitor():
    """Start the DNS monitor in background thread"""
    global monitor, monitor_status
    
    try:
        monitor_status['started_at'] = datetime.now()
        monitor = IntelligentCloudflareFailover()
        monitor_status['running'] = True
        monitor_status['error'] = None
        print("✅ DNS Monitor started successfully")
        
        # Start monitoring loop
        monitor.monitor_loop()
        
    except Exception as e:
        monitor_status['running'] = False
        monitor_status['error'] = str(e)
        print(f"❌ DNS Monitor failed: {e}")

def main():
    """Main entry point for Azure App Service with web interface"""
    global monitor_thread
    
    print("🚀 Starting Cloudflare DNS Failover with Web Interface")
    print(f"App Service: {os.getenv('WEBSITE_SITE_NAME', 'Local Development')}")
    
    # Start DNS monitor in background thread
    monitor_thread = threading.Thread(target=start_monitor, daemon=True)
    monitor_thread.start()
    
    # Start web server
    port = int(os.getenv('PORT', 8000))  # Azure App Service sets PORT
    server = HTTPServer(('0.0.0.0', port), StatusHandler)
    
    print(f"🌐 Web interface starting on port {port}")
    print(f"📊 Status available at: http://localhost:{port}/status")
    print(f"🏥 Health check at: http://localhost:{port}/health")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Server stopped")
        server.shutdown()

if __name__ == "__main__":
    main()