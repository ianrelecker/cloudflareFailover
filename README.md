# Cloudflare DNS Intelligent Failover

Simple CLI tool for automated DNS failover using Cloudflare's API with intelligent health monitoring.

## Features

- **Smart failover rules**: Ping every 30s, failover after 2 consecutive failures or >100ms latency
- **Stability requirements**: Primary must be healthy for 10 minutes before restoration  
- **Single account focus**: Simple configuration for one Cloudflare account
- **State persistence**: Remembers failover history and consecutive health checks
- **CLI-based**: Lightweight monitoring without web interface complexity

## Health Monitoring Rules

### Failover Triggers
- **Latency**: >100ms for 2 consecutive pings (60 seconds total)
- **Availability**: No response for 2 consecutive pings (60 seconds total)  
- **Check interval**: Every 30 seconds

### Restoration Requirements
- **Stability period**: Primary must be healthy for 10 minutes continuously
- **Low latency**: <100ms consistently during stability period
- **Success count**: ~20 consecutive successful health checks

## Quick Start

### 1. Get Cloudflare Credentials

1. Log into [Cloudflare Dashboard](https://dash.cloudflare.com)
2. Go to "My Profile" → "API Tokens"  
3. Create a token with `Zone:DNS:Edit` permissions for your domain
4. Note your Zone ID from the domain overview page

### 2. Configure

```bash
# Copy configuration template
cp config.json.example config.json

# Edit with your credentials
{
  "cf_api_token": "your_api_token_here",
  "cf_zone_id": "your_zone_id_here", 
  "domain": "example.com",
  "primary_ip": "1.2.3.4",
  "backup_ip": "5.6.7.8"
}
```

### 3. Install and Run

```bash
# Install dependencies
pip install -r requirements.txt

# Test configuration
./intelligent_failover.py status

# Start monitoring (runs forever)
./intelligent_failover.py monitor
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

### JSON Configuration (`config.json`)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `cf_api_token` | Cloudflare API token | Required |
| `cf_zone_id` | Cloudflare zone ID | Required |
| `domain` | Domain to manage | Required |
| `primary_ip` | Primary server IP | Required |
| `backup_ip` | Backup server IP | Required |
| `record_type` | DNS record type | "A" |
| `ttl` | DNS TTL in seconds | 120 |
| `log_file` | Log file path | "/var/log/intelligent_failover.log" |

### Environment Variables

You can also use environment variables instead of JSON:

```bash
export CF_API_TOKEN="your_token"
export CF_ZONE_ID="your_zone_id"
export DOMAIN="example.com"
export PRIMARY_IP="1.2.3.4"
export BACKUP_IP="5.6.7.8"
```

## Deployment Options

### Systemd Service

Create `/etc/systemd/system/cloudflare-failover.service`:

```ini
[Unit]
Description=Cloudflare DNS Intelligent Failover
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/intelligent_failover.py monitor
WorkingDirectory=/opt/cloudflare-failover
User=failover
Group=failover
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable cloudflare-failover
sudo systemctl start cloudflare-failover
```

### Docker Container

```bash
# Build and run with docker-compose
cd examples/docker
cp ../../config.json.example config.json
# Edit config.json with your credentials

docker-compose up -d

# Check logs
docker-compose logs -f
```

### Cron Job (Simple Checks)

For basic monitoring without the continuous monitor:

```bash
# Add to crontab - check every 2 minutes
*/2 * * * * /usr/local/bin/intelligent_failover.py check
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

The CLI design makes it easy to integrate with existing monitoring:

- **Nagios/Icinga**: Use `intelligent_failover.py status` in check scripts
- **Prometheus**: Parse JSON status output for metrics
- **Grafana**: Create dashboards from log files or status API
- **PagerDuty**: Alert on failover events from logs

## Best Practices

1. **API Security**: Use scoped API tokens with minimal `Zone:DNS:Edit` permissions
2. **Low TTL**: Keep TTL at 120 seconds for fast DNS propagation
3. **Monitoring**: Watch logs for frequent flapping between servers
4. **Testing**: Test manual failover/restore before relying on automation
5. **Backup monitoring**: Monitor the backup server health separately
6. **State backup**: Include `failover_state.json` in system backups

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

## Security Considerations

- Store API tokens securely (avoid committing to version control)
- Use minimal scope API tokens (`Zone:DNS:Edit` only)
- Run service as non-root user
- Restrict file permissions on config files (600)
- Monitor API usage for anomalies
- Rotate API tokens regularly

## License

MIT License - Use freely for personal and commercial projects.