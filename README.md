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

**Option A: Azure Key Vault (Recommended)**
```bash
# Store secrets in Azure Key Vault
az keyvault secret set --vault-name "your-vault" --name "cloudflare-api-token" --value "your_token"
az keyvault secret set --vault-name "your-vault" --name "cloudflare-zone-id" --value "your_zone_id"

# Set Key Vault URL
export AZURE_KEY_VAULT_URL="https://your-vault.vault.azure.net/"

# Note: Domain and IPs are hardcoded in the script - edit intelligent_failover.py
```

**Option B: Environment Variables Only**
```bash
export CF_API_TOKEN="your_token"
export CF_ZONE_ID="your_zone_id"

# Note: Domain and IPs are hardcoded in the script - edit intelligent_failover.py
```

### 3. Install and Run

```bash
# Install dependencies
pip install -r requirements.txt

# Edit the script to set your domain and IPs
# Update lines 127-129 in intelligent_failover.py:
#   "domain": "your-actual-domain.com"
#   "primary_ip": "your-primary-ip"
#   "backup_ip": "your-backup-ip"

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

### Configuration

| Parameter | Description | Source | Default |
|-----------|-------------|--------|----------|
| `cf_api_token` | Cloudflare API token | Azure KV or ENV | Required |
| `cf_zone_id` | Cloudflare zone ID | Azure KV or ENV | Required |
| `domain` | Domain to manage | **Hardcoded in script** | "example.com" |
| `primary_ip` | Primary server IP | **Hardcoded in script** | "1.2.3.4" |
| `backup_ip` | Backup server IP | **Hardcoded in script** | "5.6.7.8" |
| `record_type` | DNS record type | ENV | "A" |
| `ttl` | DNS TTL in seconds | ENV | 120 |
| `log_file` | Log file path | ENV | "/var/log/intelligent_failover.log" |

### Environment Variables

For sensitive credentials only (domain and IPs are hardcoded):

```bash
export CF_API_TOKEN="your_token"
export CF_ZONE_ID="your_zone_id"

# Optional settings
export RECORD_TYPE="A"
export TTL="120"
export LOG_FILE="/var/log/intelligent_failover.log"
```

### Azure Key Vault Integration

For enhanced security, store sensitive credentials in Azure Key Vault:

#### 1. Azure Key Vault Setup

```bash
# Create Key Vault (if needed)
az keyvault create --name "your-keyvault-name" --resource-group "your-rg" --location "eastus"

# Store secrets
az keyvault secret set --vault-name "your-keyvault-name" --name "cloudflare-api-token" --value "your_actual_token"
az keyvault secret set --vault-name "your-keyvault-name" --name "cloudflare-zone-id" --value "your_actual_zone_id"
```

#### 2. Authentication Methods

**Option A: Managed Identity (Recommended for Azure VMs)**
```bash
export AZURE_KEY_VAULT_URL="https://your-keyvault-name.vault.azure.net/"
# No additional auth needed - uses system assigned identity
```

**Option B: Service Principal**
```bash
export AZURE_KEY_VAULT_URL="https://your-keyvault-name.vault.azure.net/"
export AZURE_TENANT_ID="your-tenant-id"
export AZURE_CLIENT_ID="your-client-id"
export AZURE_CLIENT_SECRET="your-client-secret"
```

**Option C: Azure CLI (Development)**
```bash
az login
export AZURE_KEY_VAULT_URL="https://your-keyvault-name.vault.azure.net/"
# Uses Azure CLI credentials
```

#### 3. Custom Secret Names

Override default Key Vault secret names:

```bash
export KV_CF_API_TOKEN_NAME="my-custom-token-name"
export KV_CF_ZONE_ID_NAME="my-custom-zone-id-name"
```

#### 4. Complete Environment Configuration

```bash
# Azure Key Vault settings
export AZURE_KEY_VAULT_URL="https://your-keyvault-name.vault.azure.net/"
export AZURE_TENANT_ID="your-tenant-id"
export AZURE_CLIENT_ID="your-client-id"
export AZURE_CLIENT_SECRET="your-client-secret"

# Custom Key Vault secret names (optional)
export KV_CF_API_TOKEN_NAME="cloudflare-api-token"
export KV_CF_ZONE_ID_NAME="cloudflare-zone-id"

# Domain and IPs are hardcoded in the script
# Edit intelligent_failover.py lines 127-129 to set your values
```

**Configuration Sources:**
1. **Azure Key Vault secrets** (CF API token and zone ID only)
2. **Environment variables** (CF API token and zone ID fallback)
3. **Hardcoded in script** (domain, primary_ip, backup_ip)

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

# Make sure to edit intelligent_failover.py with your domain and IPs first!

# Option A: Using Azure Key Vault
export AZURE_KEY_VAULT_URL="https://your-vault.vault.azure.net/"
docker-compose up -d

# Option B: Using environment variables only
export CF_API_TOKEN="your_token"
export CF_ZONE_ID="your_zone_id"
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

1. **Secret Management**: Use Azure Key Vault for production deployments
2. **API Security**: Use scoped API tokens with minimal `Zone:DNS:Edit` permissions
3. **Low TTL**: Keep TTL at 120 seconds for fast DNS propagation
4. **Monitoring**: Watch logs for frequent flapping between servers
5. **Testing**: Test manual failover/restore before relying on automation
6. **Backup monitoring**: Monitor the backup server health separately
7. **State backup**: Include `failover_state.json` in system backups

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

- **Azure Key Vault**: Use for production secrets instead of environment variables
- Store API tokens securely (avoid committing to version control)
- Use minimal scope API tokens (`Zone:DNS:Edit` only)
- Run service as non-root user
- Restrict file permissions on config files (600)
- Monitor API usage for anomalies
- Rotate API tokens regularly
- Enable Key Vault access logging and monitoring

## License

MIT License - Use freely for personal and commercial projects.