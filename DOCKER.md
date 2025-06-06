# Docker Deployment Guide

This guide covers containerized deployment of the Cloudflare Intelligent Failover system.

## Quick Start

### Single Account Deployment

1. **Environment Setup**
   ```bash
   cp .env.example .env
   # Edit .env with your Cloudflare credentials
   ```

2. **Build and Run**
   ```bash
   docker build -t cloudflare-failover .
   docker run -d \
     --name cf-failover \
     --restart unless-stopped \
     --env-file .env \
     -v cf-data:/app/data \
     cloudflare-failover
   ```

3. **Monitor**
   ```bash
   docker logs -f cf-failover
   docker exec cf-failover python intelligent_failover.py status
   ```

### Multi-Account Deployment

1. **Environment Setup**
   ```bash
   cp .env.example .env
   # Add PROD_, STAGING_, DEV_ prefixed variables
   ```

2. **Deploy with Compose**
   ```bash
   docker-compose up -d
   docker-compose logs -f
   ```

## Environment Variables

### Required Variables
- `CF_API_TOKEN` - Cloudflare API token with Zone:DNS:Edit permissions
- `CF_ZONE_ID` - Cloudflare zone ID for your domain
- `DOMAIN` - Domain name to manage (e.g., api.example.com)
- `PRIMARY_IP` - Primary server IP address
- `BACKUP_IP` - Backup server IP address

### Optional Variables
- `RECORD_TYPE` - DNS record type (default: A)
- `TTL` - DNS TTL in seconds (default: 120)
- `LOG_FILE` - Log file path (default: /app/data/intelligent_failover.log)
- `STATE_FILE` - State file path (default: /app/data/failover_state.json)

## Multi-Account Configuration

For multiple Cloudflare accounts, use environment variable prefixes:

```bash
# Production account
PROD_CF_API_TOKEN=token1
PROD_CF_ZONE_ID=zone1
PROD_DOMAIN=api.example.com
PROD_PRIMARY_IP=1.2.3.4
PROD_BACKUP_IP=5.6.7.8

# Staging account  
STAGING_CF_API_TOKEN=token2
STAGING_CF_ZONE_ID=zone2
STAGING_DOMAIN=staging.example.com
STAGING_PRIMARY_IP=9.10.11.12
STAGING_BACKUP_IP=13.14.15.16
```

## Management Commands

### Status Monitoring
```bash
# Container logs
docker logs -f cloudflare-monitor-prod

# Application status
docker exec cloudflare-monitor-prod python intelligent_failover.py status

# Manual operations
docker exec cloudflare-monitor-prod python intelligent_failover.py failover
docker exec cloudflare-monitor-prod python intelligent_failover.py restore
```

### Container Management
```bash
# Start/stop services
docker-compose up -d
docker-compose stop
docker-compose restart cloudflare-monitor-prod

# Remove services and volumes
docker-compose down -v
```

## Troubleshooting

### Container Issues
```bash
# Check container status
docker ps -a

# View logs with timestamps
docker logs -f --timestamps cloudflare-monitor-prod

# Execute interactive shell
docker exec -it cloudflare-monitor-prod /bin/bash

# Check environment variables
docker exec cloudflare-monitor-prod env | grep CF_
```

### Configuration Issues
```bash
# Test configuration
docker exec cloudflare-monitor-prod python intelligent_failover.py status

# Manual health check
docker exec cloudflare-monitor-prod python intelligent_failover.py check

# View state file
docker exec cloudflare-monitor-prod cat /app/data/failover_state.json
```