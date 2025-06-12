#!/usr/bin/env python3
import requests
import sys
import logging
import json
import os
from datetime import datetime

class CloudflareFailover:
    def __init__(self, config_file="config.json"):
        self.config = self.load_config(config_file)
        self.setup_logging()
        
        self.headers = {
            "Authorization": f"Bearer {self.config['cf_api_token']}",
            "Content-Type": "application/json"
        }
        
    def load_config(self, config_file):
        """Load configuration from environment variables or hardcoded values"""
        config = {
            # Authentication - use environment variables (ideal for Azure App Service)
            "cf_api_token": os.getenv("CF_API_TOKEN", "your_cloudflare_api_token_here"),
            "cf_zone_id": os.getenv("CF_ZONE_ID", "your_cloudflare_zone_id_here"),
            
            # Domain configuration - hardcoded for simplicity
            "domain": "example.com",  # Replace with your actual domain
            "primary_ip": "20.125.26.115",  # Azure VM primary IP from bicep
            "backup_ip": "4.155.81.101",   # Azure VM backup IP from bicep
            
            # Other settings
            "record_type": os.getenv("RECORD_TYPE", "A"),
            "ttl": int(os.getenv("TTL", "120")),
            "log_file": os.getenv("LOG_FILE", "/var/log/cloudflare_failover.log")
        }
        
        # Optional config file override (backward compatibility)
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                file_config = json.load(f)
                config.update({k: v for k, v in file_config.items() if v is not None})
        
        required_fields = ["cf_api_token", "cf_zone_id", "domain", "primary_ip", "backup_ip"]
        missing_fields = [field for field in required_fields if not config.get(field) or config.get(field).startswith("your_")]
        
        if missing_fields:
            print("Please configure the following:")
            print("1. Set CF_API_TOKEN environment variable with your Cloudflare API token")
            print("2. Set CF_ZONE_ID environment variable with your Cloudflare Zone ID")
            print("3. Update the domain name in the script (line 26)")
            raise ValueError(f"Missing required configuration: {', '.join(missing_fields)}")
            
        return config
    
    def setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler(self.config.get("log_file", "/tmp/cloudflare_failover.log"))
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def get_record_id(self, name):
        """Get DNS record ID by name"""
        url = f"https://api.cloudflare.com/client/v4/zones/{self.config['cf_zone_id']}/dns_records"
        params = {"name": name, "type": self.config['record_type']}
        
        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data["success"] and data["result"]:
                return data["result"][0]["id"], data["result"][0]["content"]
            else:
                self.logger.error(f"Failed to get record: {data.get('errors', 'Unknown error')}")
                return None, None
        except requests.RequestException as e:
            self.logger.error(f"Request error: {e}")
            return None, None
    
    def update_dns_record(self, record_id, new_ip):
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
        except requests.RequestException as e:
            self.logger.error(f"Failed to update DNS record: {e}")
            return False
    
    def get_current_ip(self):
        """Get current IP from DNS record"""
        record_id, current_ip = self.get_record_id(self.config['domain'])
        return current_ip
    
    def failover_to_backup(self):
        """Switch DNS to backup server"""
        record_id, current_ip = self.get_record_id(self.config['domain'])
        
        if not record_id:
            self.logger.error("DNS record not found")
            return False
        
        if current_ip == self.config['backup_ip']:
            self.logger.info("Already pointing to backup IP")
            return True
        
        success = self.update_dns_record(record_id, self.config['backup_ip'])
        if success:
            self.logger.info(f"Successfully failed over to backup IP: {self.config['backup_ip']}")
        else:
            self.logger.error("Failed to update DNS to backup IP")
        
        return success
    
    def restore_to_primary(self):
        """Switch DNS back to primary server"""
        record_id, current_ip = self.get_record_id(self.config['domain'])
        
        if not record_id:
            self.logger.error("DNS record not found")
            return False
        
        if current_ip == self.config['primary_ip']:
            self.logger.info("Already pointing to primary IP")
            return True
        
        success = self.update_dns_record(record_id, self.config['primary_ip'])
        if success:
            self.logger.info(f"Successfully restored to primary IP: {self.config['primary_ip']}")
        else:
            self.logger.error("Failed to update DNS to primary IP")
        
        return success
    
    def check_and_failover(self):
        """Check primary server health and failover if needed"""
        import subprocess
        
        try:
            result = subprocess.run(
                ["ping", "-c", "3", "-W", "3", self.config['primary_ip']], 
                capture_output=True, 
                timeout=10
            )
            
            if result.returncode == 0:
                self.logger.info("Primary server is healthy")
                return self.restore_to_primary()
            else:
                self.logger.warning("Primary server is down")
                return self.failover_to_backup()
                
        except subprocess.TimeoutExpired:
            self.logger.warning("Primary server ping timed out")
            return self.failover_to_backup()
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            return False

def main():
    if len(sys.argv) < 2:
        print("Usage: cloudflare_failover.py [failover|restore|check|status]")
        print("  failover - Switch to backup server")
        print("  restore  - Switch to primary server")
        print("  check    - Health check and auto-failover")
        print("  status   - Show current DNS target")
        sys.exit(1)
    
    action = sys.argv[1].lower()
    
    try:
        cf = CloudflareFailover()
        
        if action == "failover":
            success = cf.failover_to_backup()
        elif action == "restore":
            success = cf.restore_to_primary()
        elif action == "check":
            success = cf.check_and_failover()
        elif action == "status":
            current_ip = cf.get_current_ip()
            if current_ip:
                print(f"Current DNS target: {current_ip}")
                if current_ip == cf.config['primary_ip']:
                    print("Status: Primary")
                elif current_ip == cf.config['backup_ip']:
                    print("Status: Backup")
                else:
                    print("Status: Unknown")
                success = True
            else:
                print("Failed to get current status")
                success = False
        else:
            print(f"Unknown action: {action}")
            success = False
        
        sys.exit(0 if success else 1)
        
    except Exception as e:
        logging.error(f"Script failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()