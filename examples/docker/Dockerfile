FROM python:3.11-alpine

# Install system dependencies
RUN apk add --no-cache \
    curl \
    iputils \
    bash

# Create non-root user
RUN addgroup -g 1000 failover && \
    adduser -u 1000 -G failover -s /bin/bash -D failover

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy scripts
COPY intelligent_failover.py .
COPY cloudflare_failover.py .
COPY cloudflare_failover.sh .
RUN chmod +x *.py *.sh

# Create data and log directories
RUN mkdir -p /app/data /var/log && \
    chown -R failover:failover /app /var/log

# Switch to non-root user
USER failover

# Default command - start monitoring
CMD ["python", "intelligent_failover.py", "monitor"]