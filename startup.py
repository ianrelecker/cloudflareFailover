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

if __name__ == "__main__":
    main()