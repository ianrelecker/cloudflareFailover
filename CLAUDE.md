# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Start for Azure App Service

1. **Configure your domain and IPs** in `intelligent_failover.py` (lines 129-131)
2. **Deploy to Azure App Service** using continuous deployment from GitHub
3. **Set Environment Variables** in App Service Configuration:
   - `CF_API_TOKEN`: Your Cloudflare API token
   - `CF_ZONE_ID`: Your Cloudflare Zone ID
4. **Set Startup Command**: `python startup.py`
5. **Monitor**: Check Azure App Service logs for operation status

📖 **Complete guide**: See `azure-app-service.md`

## Project Overview

This is a DNS failover automation system designed for **Azure App Service** that monitors server health and automatically switches Cloudflare DNS records between primary and backup servers. The project has two main implementations:

- `cloudflare_failover.py` - Basic failover with simple ping checks
- `intelligent_failover.py` - Advanced version with intelligent monitoring and state persistence
- `startup.py` - Azure App Service entry point script

## Architecture

### Core Components

**Health Monitoring Logic (Intelligent Version):**
- Ping checks every 30 seconds
- Failover triggers: 2 consecutive failures OR >100ms latency for 2 consecutive checks
- Restoration requires: 10 minutes continuous health (<100ms latency, ~20 successful checks)
- State persistence in `failover_state.json` with last 100 health check records

**Configuration Pattern (Azure App Service Optimized):**
1. Environment variables in Azure App Service Configuration
2. Hardcoded domain and server IPs in scripts
3. Auto-detection of Azure App Service environment

**API Integration:**
- Cloudflare API v4 for DNS management
- Requires Zone:DNS:Edit permissions only
- Uses 120 second TTL for fast DNS propagation

### State Management

The intelligent version maintains state in `failover_state.json` containing:
- Consecutive failure/success counts
- Current DNS state (primary/backup)
- Historical health check records
- Failover event history

## Common Development Commands

### Azure App Service Commands
```bash
# Main startup script (configured in App Service)
python startup.py

# Manual testing locally
python intelligent_failover.py status
python intelligent_failover.py check
```

### Local Development
```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export CF_API_TOKEN="your_token"
export CF_ZONE_ID="your_zone_id"

# Run locally
python startup.py
```

### Docker Operations
```bash
# Build and run with docker-compose
cd examples/docker
docker-compose up -d

# View logs
docker-compose logs -f cloudflare-failover
```

## Configuration Requirements

### Azure App Service Configuration
**Required Application Settings:**
- `CF_API_TOKEN`: Your Cloudflare API token (Zone:DNS:Edit permissions)
- `CF_ZONE_ID`: Your Cloudflare Zone ID

**Optional Application Settings:**
- `LOG_LEVEL`: INFO (default), DEBUG, WARNING, ERROR
- `TTL`: 120 (default DNS record TTL in seconds)

**Startup Command:**
```
python startup.py
```

### Domain Configuration
**Before deploying to Azure App Service**, edit the scripts:

**intelligent_failover.py** (lines 129-131):
```python
"domain": "yourdomain.com",        # Your actual domain
"primary_ip": "20.125.26.115",    # Your primary server IP
"backup_ip": "4.155.81.101",      # Your backup server IP
```

**cloudflare_failover.py** (lines 27-29):
```python
"domain": "yourdomain.com",        # Your actual domain
"primary_ip": "20.125.26.115",    # Your primary server IP
"backup_ip": "4.155.81.101",      # Your backup server IP
```

## Deployment Options

### Azure App Service (Primary Deployment Method)
- **Startup Command**: `python startup.py`
- **Runtime**: Python 3.11 on Linux
- **Configuration**: Environment variables in App Service settings
- **Continuous Deployment**: GitHub integration
- **Monitoring**: Built-in Azure logging and health checks
- See `azure-app-service.md` for complete deployment guide

### Docker (Development/Testing)
- Use `examples/docker/docker-compose.yml` for local testing
- Environment variables via `.env` file
- Health checks included

### Legacy Options (Not Recommended for Production)
- Systemd: `examples/systemd/`
- Cron: `examples/crontab.example`

## Infrastructure as Code

`main.bicep` contains complete Azure infrastructure definition:
- Creates 2 VMs (primary: 20.125.26.115, backup: 4.155.81.101)
- Configures networking, security groups, and public IPs
- SSH, HTTP, and ICMP access rules

## Key Files to Understand

### Production Files
- `startup.py` - **Azure App Service entry point**
- `intelligent_failover.py` - Main production script with advanced logic
- `failover_state.json` - Runtime state file (created in `/tmp/` for App Service)
- `requirements.txt` - Python dependencies (simplified for App Service)
- `azure-app-service.md` - **Complete deployment guide**

### Development/Testing
- `cloudflare_failover.py` - Basic failover script
- `examples/docker/` - Docker configuration for local testing
- `examples/systemd/` - Legacy systemd configuration

## Security Notes

### Azure App Service Security
- API tokens stored securely in App Service Configuration (encrypted at rest)
- Cloudflare token requires only Zone:DNS:Edit permissions
- App Service provides built-in security features
- HTTPS endpoints automatically available
- No file system persistence (state stored in `/tmp/`)

### Best Practices
- Use minimal Cloudflare API token permissions
- Monitor App Service logs for security events
- Consider Azure Key Vault for additional secret management
- Enable App Service authentication if external access needed