# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a DNS failover automation system that monitors server health and automatically switches Cloudflare DNS records between primary and backup servers. The project has two main implementations:

- `cloudflare_failover.py` - Basic failover with simple ping checks
- `intelligent_failover.py` - Advanced version with intelligent monitoring and state persistence

## Architecture

### Core Components

**Health Monitoring Logic (Intelligent Version):**
- Ping checks every 30 seconds
- Failover triggers: 2 consecutive failures OR >100ms latency for 2 consecutive checks
- Restoration requires: 10 minutes continuous health (<100ms latency, ~20 successful checks)
- State persistence in `failover_state.json` with last 100 health check records

**Configuration Pattern:**
1. Environment variables (recommended for Azure App Service)
2. Hardcoded values in script (domain, primary_ip, backup_ip)

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

### Setup and Testing
```bash
# Install dependencies
pip install -r requirements.txt

# Test configuration
./intelligent_failover.py status

# Single health check
./intelligent_failover.py check

# Manual operations
./intelligent_failover.py failover
./intelligent_failover.py restore
```

### Running the Monitor
```bash
# Continuous monitoring (main operation)
./intelligent_failover.py monitor

# With environment variables
CF_API_TOKEN="token" CF_ZONE_ID="zone_id" ./intelligent_failover.py monitor
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

### Credentials Setup
**Environment Variables (Recommended for Azure App Service)**
```bash
export CF_API_TOKEN="your_cloudflare_token"
export CF_ZONE_ID="your_zone_id"
```

### Domain Configuration
Edit the script directly to set your domain and server IPs:
- `intelligent_failover.py` lines 129-131 (domain, primary_ip, backup_ip)
- `cloudflare_failover.py` lines 27-29 (domain, primary_ip, backup_ip)

## Deployment Options

### Docker (Recommended)
- Use `examples/docker/docker-compose.yml`
- Uses environment variable authentication
- Includes health checks and restart policies

### Systemd
- Service file: `examples/systemd/cloudflare-monitor.service`
- Timer file: `examples/systemd/cloudflare-monitor.timer`
- Runs with hardened security settings and non-root user

### Cron
- Example: `examples/crontab.example`
- Simple scheduled execution for basic monitoring

## Infrastructure as Code

`main.bicep` contains complete Azure infrastructure definition:
- Creates 2 VMs (primary: 20.125.26.115, backup: 4.155.81.101)
- Configures networking, security groups, and public IPs
- SSH, HTTP, and ICMP access rules

## Key Files to Understand

- `intelligent_failover.py` - Main production script with advanced logic
- `failover_state.json` - Runtime state file (created automatically)
- `config.json.example` - Configuration template
- `examples/` - Various deployment configurations
- `requirements.txt` - Python dependencies

## Security Notes

- API tokens should be stored as environment variables in Azure App Service
- Cloudflare token needs only Zone:DNS:Edit permissions
- Container runs as non-root user
- Systemd service uses hardened security settings