# Azure App Service Deployment Guide

This guide covers deploying the Cloudflare DNS Failover system to Azure App Service with continuous deployment.

## Prerequisites

1. Azure subscription
2. Cloudflare account with API token
3. GitHub repository (for continuous deployment)

## Step 1: Configure Your Cloudflare API Token

1. Go to [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens)
2. Create a custom token with:
   - **Permissions**: Zone:DNS:Edit
   - **Zone Resources**: Include your specific zone
3. Copy the API token

## Step 2: Get Your Zone ID

1. Go to your domain in Cloudflare dashboard
2. In the right sidebar, copy the "Zone ID"

## Step 3: Update Domain Configuration

Edit the domain and server IPs in `intelligent_failover.py` (lines 129-131):
```python
"domain": "yourdomain.com",           # Your actual domain
"primary_ip": "20.125.26.115",       # Your primary server IP
"backup_ip": "4.155.81.101",         # Your backup server IP
```

## Step 4: Create Azure App Service

### Option A: Azure Portal

1. Create a new **Web App**
2. Configure:
   - **Runtime**: Python 3.11
   - **Operating System**: Linux
   - **Region**: Choose based on your needs
   - **App Service Plan**: Basic B1 or higher recommended

### Option B: Azure CLI

```bash
# Create resource group
az group create --name rg-cloudflare-failover --location eastus

# Create App Service plan
az appservice plan create \
  --name plan-cloudflare-failover \
  --resource-group rg-cloudflare-failover \
  --sku B1 \
  --is-linux

# Create Web App
az webapp create \
  --name app-cloudflare-failover \
  --resource-group rg-cloudflare-failover \
  --plan plan-cloudflare-failover \
  --runtime "PYTHON|3.11"
```

## Step 5: Configure Environment Variables

In Azure Portal, go to your App Service → **Configuration** → **Application Settings**:

| Name | Value |
|------|-------|
| `CF_API_TOKEN` | Your Cloudflare API token |
| `CF_ZONE_ID` | Your Cloudflare Zone ID |
| `LOG_LEVEL` | `INFO` (optional) |
| `TTL` | `120` (optional) |

## Step 6: Set Up Continuous Deployment

### Option A: GitHub Actions (Recommended)

1. In Azure Portal, go to **Deployment Center**
2. Choose **GitHub**
3. Authenticate with GitHub
4. Select your repository and branch
5. Azure will create a GitHub Action workflow

### Option B: GitHub Integration

1. Go to **Deployment Center** → **GitHub**
2. Authenticate and select repository
3. Choose deployment method: **GitHub Actions**

## Step 7: Configure Startup Command

In Azure Portal, go to **Configuration** → **General Settings**:

**Startup Command**: `python startup.py`

This runs the failover monitoring service continuously. For debugging, you can also use `python app.py` to run the web interface with status dashboard.

## Step 8: Deploy

1. Commit your changes to GitHub
2. Push to the configured branch
3. Monitor deployment in Azure Portal → **Deployment Center**

## Step 9: Verify Deployment

1. Check **Log stream** in Azure Portal for startup messages
2. Test the service:
   ```bash
   curl https://your-app-name.azurewebsites.net
   ```

## Monitoring and Troubleshooting

### View Logs
- **Azure Portal**: App Service → **Log stream**
- **Azure CLI**: `az webapp log tail --name your-app-name --resource-group your-rg`

### Health Check
Monitor the service via Azure App Service logs and the optional web interface.

### Common Issues

1. **Missing Environment Variables**: Verify CF_API_TOKEN and CF_ZONE_ID in Application Settings
2. **Domain Not Configured**: Update domain configuration in intelligent_failover.py
3. **API Permissions**: Ensure Cloudflare API token has Zone:DNS:Edit permissions
4. **Startup Failures**: Check logs for Python dependency or configuration errors

## Security Considerations

- Store API tokens only in Azure App Service Configuration (encrypted)
- Use Cloudflare API tokens with minimal required permissions
- Enable Azure App Service authentication if needed
- Consider using Azure Key Vault for additional security

## Scaling

- **Basic tier**: Suitable for single-instance monitoring
- **Standard tier**: Supports auto-scaling (though not needed for this use case)
- **Premium tier**: Additional security and performance features

## Cost Optimization

- Use **Basic B1** tier for cost-effective monitoring
- Consider **Free tier** for development/testing (with limitations)
- Monitor usage with Azure Cost Management