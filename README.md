# Cloudflare DNS Failover

Automated DNS failover system for Azure App Service that monitors server health and switches Cloudflare DNS records between primary and backup servers.

## Features

- **Smart monitoring**: Health checks every 30 seconds with intelligent failover logic
- **Stable restoration**: 10-minute stability requirement before restoring to primary
- **Azure optimized**: Designed for Azure App Service with environment variable configuration
- **State persistence**: Maintains failover history and health check records
- **Multiple interfaces**: CLI tool and optional web dashboard

## Health Monitoring

### Failover Triggers
- 2 consecutive failures (60 seconds)
- Latency >100ms for 2 consecutive checks (60 seconds)

### Restoration Requirements
- Primary healthy for 10 minutes continuously
- Latency <100ms throughout stability period
- ~20 consecutive successful health checks

## Quick Start

### Azure App Service Deployment (Recommended)

1. **Configure domain and IPs** in `intelligent_failover.py` (lines 129-131)
2. **Create Azure App Service** with Python 3.11 runtime
3. **Set environment variables** in App Service Configuration:
   - `CF_API_TOKEN`: Your Cloudflare API token
   - `CF_ZONE_ID`: Your Cloudflare Zone ID
4. **Set startup command**: `python startup.py`
5. **Deploy** using GitHub Actions or continuous deployment

📖 **Complete deployment guide**: See `azure-app-service.md`

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export CF_API_TOKEN="your_token"
export CF_ZONE_ID="your_zone_id"

# Configure domain and IPs in intelligent_failover.py

# Test configuration
python intelligent_failover.py status

# Start monitoring
python intelligent_failover.py monitor
```

## Usage

### Commands

```bash
./intelligent_failover.py [command]

Commands:
  monitor   - Start continuous monitoring (main command)
  status    - Show current status and health check history
  failover  - Manual failover to backup IP
  restore   - Manual restore to primary IP  
  check     - Single health check (for cron jobs)
```

### Example Status Output

```json
{
  "domain": "api.example.com",
  "current_ip": "1.2.3.4",
  "primary_ip": "1.2.3.4", 
  "backup_ip": "5.6.7.8",
  "is_failed_over": false,
  "consecutive_failures": 0,
  "consecutive_successes": 15,
  "last_check": "2024-01-15T10:30:00",
  "last_success": true,
  "last_latency_ms": 45.2,
  "health_checks_total": 2847
}
```

## Configuration

### Configuration

| Parameter | Description | Source | Default |
|-----------|-------------|--------|----------|
| `CF_API_TOKEN` | Cloudflare API token | Environment variable | Required |
| `CF_ZONE_ID` | Cloudflare zone ID | Environment variable | Required |
| `domain` | Domain to manage | Hardcoded in script | "yourdomain.com" |
| `primary_ip` | Primary server IP | Hardcoded in script | "20.125.26.115" |
| `backup_ip` | Backup server IP | Hardcoded in script | "4.155.81.101" |
| `TTL` | DNS TTL in seconds | Environment variable | 120 |
| `LOG_LEVEL` | Logging level | Environment variable | INFO |

**Required Environment Variables:**
```bash
CF_API_TOKEN="your_cloudflare_api_token"
CF_ZONE_ID="your_cloudflare_zone_id"
```

**Domain Configuration (Edit in Code):**
Update `intelligent_failover.py` lines 129-131:
```python
"domain": "yourdomain.com",
"primary_ip": "your-primary-ip",
"backup_ip": "your-backup-ip",
```

## Deployment Options

### Azure App Service (Recommended)
- **Primary deployment method** for production
- Continuous deployment from GitHub
- Built-in monitoring and logging
- Auto-scaling and high availability
- See `azure-app-service.md` for complete guide

### Docker Container
```bash
cd examples/docker
export CF_API_TOKEN="your_token"
export CF_ZONE_ID="your_zone_id"
docker-compose up -d
```

### Local Development
```bash
pip install -r requirements.txt
python startup.py
```

## State Management

The system maintains state in `failover_state.json`:

- **Health check history**: Last 100 ping results with timestamps and latency
- **Consecutive counters**: Tracks failure/success streaks for decision making
- **Failover history**: Records when failovers and restores occurred
- **Current status**: Tracks whether currently failed over

This state persists across restarts, so the system remembers its history and doesn't reset stability counters.

## Monitoring and Alerts

### Log Output

The system logs all actions with structured messages:

```
2024-01-15 10:30:00 - INFO - Health check - Success: True, Latency: 45.2ms, Consecutive failures: 0, Consecutive successes: 15
2024-01-15 10:30:30 - WARNING - High latency detected: 150.3ms  
2024-01-15 10:31:00 - WARNING - Failing over to backup IP 5.6.7.8
2024-01-15 10:31:00 - INFO - Successfully failed over to backup
```

### Integration with Monitoring Systems

- **Azure Monitor**: Built-in logging and metrics for App Service deployments
- **Application Insights**: Performance monitoring and alerting
- **External monitoring**: JSON status endpoint at `/status` for integrations
- **Log analysis**: Structured logging for automated alert parsing

## Best Practices

1. **Use Azure App Service** for production deployments with built-in security
2. **Minimal API permissions**: Cloudflare tokens with only `Zone:DNS:Edit` permissions
3. **Fast DNS propagation**: Use 120-second TTL for quick failover
4. **Monitor logs** for frequent failover events indicating issues
5. **Test failover** manually before relying on automation
6. **Monitor both servers** independently to verify health

## Troubleshooting

### Common Issues

**"DNS record not found"**
- Verify domain exists in Cloudflare with the correct record type
- Check that zone ID matches the domain

**"Request error"** 
- Verify API token has `Zone:DNS:Edit` permissions
- Check token hasn't expired

**"High latency but server responsive"**
- May indicate network congestion rather than server failure
- Consider adjusting latency threshold if needed

### Debug Mode

Enable detailed logging by checking the log file:

```bash
tail -f /var/log/intelligent_failover.log
```

Or run a single check to see immediate output:

```bash
./intelligent_failover.py check
```

## Security

- **Azure App Service**: Environment variables encrypted at rest
- **Minimal API permissions**: `Zone:DNS:Edit` only
- **No secrets in code**: All sensitive data via environment variables
- **HTTPS by default**: Azure App Service provides automatic SSL
- **Regular token rotation**: Update Cloudflare API tokens periodically

## License

MIT License - Use freely for personal and commercial projects.