#!/bin/bash

# Cloudflare DNS Failover Script
# Simple bash implementation for basic failover functionality

set -euo pipefail

# Configuration - can be overridden by environment variables or config file
CONFIG_FILE="${CONFIG_FILE:-./config.env}"
LOG_FILE="${LOG_FILE:-/var/log/cloudflare_failover.log}"

# Source config file if it exists
[[ -f "$CONFIG_FILE" ]] && source "$CONFIG_FILE"

# Required configuration
CF_API_TOKEN="${CF_API_TOKEN:-}"
CF_ZONE_ID="${CF_ZONE_ID:-}"
DOMAIN="${DOMAIN:-}"
PRIMARY_IP="${PRIMARY_IP:-}"
BACKUP_IP="${BACKUP_IP:-}"

# Optional configuration
RECORD_TYPE="${RECORD_TYPE:-A}"
TTL="${TTL:-120}"
PING_COUNT="${PING_COUNT:-3}"
PING_TIMEOUT="${PING_TIMEOUT:-3}"

# Logging function
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" | tee -a "$LOG_FILE"
}

# Check if required tools are available
check_dependencies() {
    local missing_deps=()
    
    command -v curl >/dev/null 2>&1 || missing_deps+=("curl")
    command -v jq >/dev/null 2>&1 || missing_deps+=("jq")
    command -v ping >/dev/null 2>&1 || missing_deps+=("ping")
    
    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        log "ERROR" "Missing required dependencies: ${missing_deps[*]}"
        log "INFO" "Please install: sudo apt-get install curl jq iputils-ping"
        exit 1
    fi
}

# Validate configuration
validate_config() {
    local missing_config=()
    
    [[ -z "$CF_API_TOKEN" ]] && missing_config+=("CF_API_TOKEN")
    [[ -z "$CF_ZONE_ID" ]] && missing_config+=("CF_ZONE_ID")
    [[ -z "$DOMAIN" ]] && missing_config+=("DOMAIN")
    [[ -z "$PRIMARY_IP" ]] && missing_config+=("PRIMARY_IP")
    [[ -z "$BACKUP_IP" ]] && missing_config+=("BACKUP_IP")
    
    if [[ ${#missing_config[@]} -gt 0 ]]; then
        log "ERROR" "Missing required configuration: ${missing_config[*]}"
        exit 1
    fi
}

# Get DNS record information
get_record_info() {
    local response
    response=$(curl -s -X GET \
        "https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/dns_records?name=$DOMAIN&type=$RECORD_TYPE" \
        -H "Authorization: Bearer $CF_API_TOKEN" \
        -H "Content-Type: application/json")
    
    if ! echo "$response" | jq -e '.success' >/dev/null 2>&1; then
        log "ERROR" "Failed to get DNS record: $(echo "$response" | jq -r '.errors[0].message // "Unknown error"')"
        return 1
    fi
    
    local record_count
    record_count=$(echo "$response" | jq -r '.result | length')
    
    if [[ "$record_count" -eq 0 ]]; then
        log "ERROR" "No DNS record found for $DOMAIN"
        return 1
    fi
    
    echo "$response" | jq -r '.result[0]'
}

# Update DNS record
update_dns_record() {
    local record_id="$1"
    local new_ip="$2"
    
    local response
    response=$(curl -s -X PUT \
        "https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/dns_records/$record_id" \
        -H "Authorization: Bearer $CF_API_TOKEN" \
        -H "Content-Type: application/json" \
        --data "{
            \"type\": \"$RECORD_TYPE\",
            \"name\": \"$DOMAIN\",
            \"content\": \"$new_ip\",
            \"ttl\": $TTL,
            \"proxied\": false
        }")
    
    if echo "$response" | jq -e '.success' >/dev/null 2>&1; then
        log "INFO" "Successfully updated DNS record to $new_ip"
        return 0
    else
        log "ERROR" "Failed to update DNS record: $(echo "$response" | jq -r '.errors[0].message // "Unknown error"')"
        return 1
    fi
}

# Check server health
check_server_health() {
    local ip="$1"
    local server_name="$2"
    
    log "INFO" "Checking health of $server_name ($ip)"
    
    if ping -c "$PING_COUNT" -W "$PING_TIMEOUT" "$ip" >/dev/null 2>&1; then
        log "INFO" "$server_name is healthy"
        return 0
    else
        log "WARNING" "$server_name is not responding to ping"
        return 1
    fi
}

# Get current DNS target
get_current_target() {
    local record_info
    if record_info=$(get_record_info); then
        echo "$record_info" | jq -r '.content'
    else
        return 1
    fi
}

# Failover to backup
failover_to_backup() {
    log "INFO" "Initiating failover to backup server"
    
    local record_info current_ip record_id
    if ! record_info=$(get_record_info); then
        return 1
    fi
    
    current_ip=$(echo "$record_info" | jq -r '.content')
    record_id=$(echo "$record_info" | jq -r '.id')
    
    if [[ "$current_ip" == "$BACKUP_IP" ]]; then
        log "INFO" "Already pointing to backup IP ($BACKUP_IP)"
        return 0
    fi
    
    if update_dns_record "$record_id" "$BACKUP_IP"; then
        log "INFO" "Failover completed successfully"
        return 0
    else
        return 1
    fi
}

# Restore to primary
restore_to_primary() {
    log "INFO" "Initiating restore to primary server"
    
    local record_info current_ip record_id
    if ! record_info=$(get_record_info); then
        return 1
    fi
    
    current_ip=$(echo "$record_info" | jq -r '.content')
    record_id=$(echo "$record_info" | jq -r '.id')
    
    if [[ "$current_ip" == "$PRIMARY_IP" ]]; then
        log "INFO" "Already pointing to primary IP ($PRIMARY_IP)"
        return 0
    fi
    
    if update_dns_record "$record_id" "$PRIMARY_IP"; then
        log "INFO" "Restore completed successfully"
        return 0
    else
        return 1
    fi
}

# Health check and auto-failover
health_check_and_failover() {
    log "INFO" "Starting health check and auto-failover"
    
    if check_server_health "$PRIMARY_IP" "Primary server"; then
        # Primary is healthy, ensure we're pointing to it
        restore_to_primary
    else
        # Primary is down, failover to backup
        log "WARNING" "Primary server failed health check, failing over to backup"
        failover_to_backup
    fi
}

# Show current status
show_status() {
    local current_ip
    if current_ip=$(get_current_target); then
        echo "Current DNS target: $current_ip"
        
        if [[ "$current_ip" == "$PRIMARY_IP" ]]; then
            echo "Status: Primary"
        elif [[ "$current_ip" == "$BACKUP_IP" ]]; then
            echo "Status: Backup"
        else
            echo "Status: Unknown (not primary or backup)"
        fi
        
        return 0
    else
        echo "Failed to get current status"
        return 1
    fi
}

# Usage information
usage() {
    cat << EOF
Usage: $0 [COMMAND]

Commands:
    failover    Switch DNS to backup server
    restore     Switch DNS to primary server
    check       Perform health check and auto-failover
    status      Show current DNS configuration
    help        Show this help message

Configuration:
    Set these environment variables or create a config.env file:
    - CF_API_TOKEN: Cloudflare API token
    - CF_ZONE_ID: Cloudflare zone ID
    - DOMAIN: Domain name to manage
    - PRIMARY_IP: Primary server IP address
    - BACKUP_IP: Backup server IP address

Optional configuration:
    - RECORD_TYPE: DNS record type (default: A)
    - TTL: DNS TTL in seconds (default: 120)
    - PING_COUNT: Number of ping attempts (default: 3)
    - PING_TIMEOUT: Ping timeout in seconds (default: 3)
    - LOG_FILE: Log file path (default: /var/log/cloudflare_failover.log)

Examples:
    $0 status
    $0 check
    $0 failover
    $0 restore
EOF
}

# Main function
main() {
    local command="${1:-help}"
    
    case "$command" in
        "failover")
            check_dependencies
            validate_config
            failover_to_backup
            ;;
        "restore")
            check_dependencies
            validate_config
            restore_to_primary
            ;;
        "check")
            check_dependencies
            validate_config
            health_check_and_failover
            ;;
        "status")
            check_dependencies
            validate_config
            show_status
            ;;
        "help"|"-h"|"--help")
            usage
            exit 0
            ;;
        *)
            echo "Unknown command: $command"
            usage
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"