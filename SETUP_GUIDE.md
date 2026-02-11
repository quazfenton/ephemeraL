# Cloud Terminal Platform - Setup Guide

This guide will walk you through setting up a production-grade cloud terminal platform similar to Zo.computer.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [System Setup](#system-setup)
3. [Identity Provider Setup](#identity-provider-setup)
4. [Platform Installation](#platform-installation)
5. [Testing](#testing)
6. [Production Deployment](#production-deployment)

## Prerequisites

### Required Software

- **Operating System**: Linux (Ubuntu 22.04+ recommended)
- **Docker**: Version 20.10+
- **Python**: Version 3.11+
- **Bash**: Version 4.0+
- **zstd**: Compression tool for snapshots

### Install Prerequisites (Ubuntu)

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Install Python and pip
sudo apt install -y python3.11 python3.11-venv python3-pip

# Install zstd for compression
sudo apt install -y zstd

# Log out and back in for Docker group to take effect
```

## System Setup

### 1. Create Directory Structure

```bash
# Create base directories
sudo mkdir -p /srv/workspaces
sudo mkdir -p /srv/snapshots

# Set permissions (adjust as needed for your setup)
sudo chown -R $USER:$USER /srv/workspaces
sudo chown -R $USER:$USER /srv/snapshots
```

### 2. Clone/Copy Platform Files

```bash
# Navigate to your project directory
cd /home/ubuntu/cloud-terminal-platform

# Verify all files are present
ls -la
```

## Identity Provider Setup

You need to choose and configure an identity provider. Here are the options:

### Option 1: Auth0 (Recommended for Production)

1. Sign up at [auth0.com](https://auth0.com)
2. Create a new application
3. Configure allowed callback URLs
4. Download the public key from your Auth0 tenant
5. Save it as `public_key.pem` in the project directory

### Option 2: Clerk (Developer-Friendly)

1. Sign up at [clerk.com](https://clerk.com)
2. Create a new application
3. Get your JWT public key from the dashboard
4. Save it as `public_key.pem`

### Option 3: Supabase Auth (Open Source)

1. Create a Supabase project at [supabase.com](https://supabase.com)
2. Enable authentication
3. Get JWT secret from project settings
4. Configure accordingly

### Option 4: Keycloak (Self-Hosted)

1. Deploy Keycloak server
2. Create a realm and client
3. Export public key
4. Configure client settings

### Configure the Platform

Edit `auth.py` and replace the placeholder with your actual public key:

```python
PUBLIC_KEY = """
-----BEGIN PUBLIC KEY-----
YOUR_ACTUAL_PUBLIC_KEY_HERE
-----END PUBLIC KEY-----
"""
```

## Platform Installation

### 1. Create Virtual Environment

```bash
python3.11 -m venv venv
source venv/bin/activate
```

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your settings
nano .env
```

### 4. Test Container Management

```bash
# Create a test container
./manage_container.sh create u_test_123

# Check status
./manage_container.sh status u_test_123

# Stop container
./manage_container.sh stop u_test_123
```

### 5. Test Snapshot Operations

```bash
# Create a test snapshot
./create_snapshot.sh u_test_123 snap_test_001

# List snapshots
ls -lh /srv/snapshots/u_test_123/

# Restore snapshot
./restore_snapshot.sh u_test_123 snap_test_001
```

## Testing

### 1. Start the API Server

```bash
# Activate virtual environment if not already active
source venv/bin/activate

# Start server
python snapshot_api.py
```

The API will be available at `http://localhost:8000`

### 2. Test API Endpoints

#### Create Snapshot

```bash
curl -X POST http://localhost:8000/snapshot/create \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{}'
```

#### List Snapshots

```bash
curl http://localhost:8000/snapshot/list \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

#### Restore Snapshot

```bash
curl -X POST http://localhost:8000/snapshot/restore \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{
    "snapshot_id": "snap_test_001"
  }'
```

### 3. View API Documentation

Open your browser and navigate to:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Production Deployment

### 1. Use Process Manager

Install and configure systemd service:

```bash
sudo nano /etc/systemd/system/cloud-terminal-api.service
```

Add:

```ini
[Unit]
Description=Cloud Terminal Platform API
After=network.target docker.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/cloud-terminal-platform
Environment="PATH=/home/ubuntu/cloud-terminal-platform/venv/bin"
ExecStart=/home/ubuntu/cloud-terminal-platform/venv/bin/python snapshot_api.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable cloud-terminal-api
sudo systemctl start cloud-terminal-api
sudo systemctl status cloud-terminal-api
```

### 2. Configure Reverse Proxy (Nginx)

```bash
sudo apt install -y nginx
sudo nano /etc/nginx/sites-available/cloud-terminal
```

Add:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable site:

```bash
sudo ln -s /etc/nginx/sites-available/cloud-terminal /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 3. Setup SSL with Let's Encrypt

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

### 4. Configure Firewall

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### 5. Setup Monitoring

Consider adding:
- Log aggregation (ELK stack, Loki)
- Metrics collection (Prometheus)
- Alerting (Alertmanager)
- Uptime monitoring

### 6. Backup Strategy

```bash
# Install AWS CLI
sudo apt update
sudo apt install -y awscli

# Configure AWS credentials (choose one of the following methods):
# Method 1: Interactive configuration
aws configure

# Method 2: Environment variables
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_DEFAULT_REGION=your_region

# Method 3: IAM Role (recommended for EC2 instances)

# Create backup script
cat > /home/ubuntu/backup_snapshots.sh << 'EOF'
#!/bin/bash
# Backup all snapshots to S3 or remote storage
# Create logs directory if it doesn't exist
mkdir -p /home/ubuntu/logs
# Log output and errors for monitoring
aws s3 sync /srv/snapshots/ s3://your-bucket/snapshots/ >> /home/ubuntu/logs/snapshot-backup.log 2>&1
EOF

chmod +x /home/ubuntu/backup_snapshots.sh

# Add to crontab for daily backups with logging
crontab -e
# Add: 0 2 * * * /home/ubuntu/backup_snapshots.sh >> /home/ubuntu/logs/cron-snapshot-backup.log 2>&1
```

## Troubleshooting

### Container Won't Start

```bash
# Check Docker status
sudo systemctl status docker

# View container logs
docker logs shell-u_123

# Restart Docker
sudo systemctl restart docker
```

### Snapshot Creation Fails

```bash
# Check disk space
df -h

# Check permissions
ls -la /srv/snapshots/

# Check zstd installation
which zstd
```

### API Not Responding

```bash
# Check if service is running
sudo systemctl status cloud-terminal-api

# View logs
sudo journalctl -u cloud-terminal-api -f

# Check port availability
sudo netstat -tlnp | grep 8000
```

## Next Steps

1. **Implement Authentication Middleware**: Add JWT validation to all API endpoints
2. **Add Rate Limiting**: Prevent abuse with rate limiting
3. **Implement Usage Metering**: Track resource usage per user
4. **Add WebSocket Support**: For real-time terminal access
5. **Setup Load Balancing**: For horizontal scaling
6. **Implement Auto-scaling**: Based on demand
7. **Add Cross-region Replication**: For disaster recovery

## Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Docker Documentation](https://docs.docker.com/)
- [JWT Best Practices](https://tools.ietf.org/html/rfc8725)
- [Nginx Configuration](https://nginx.org/en/docs/)

## Support

For issues and questions, refer to:
- [Original conversation](https://chatgpt.com/share/695a0e7f-dd14-8004-a308-d54851120225)
- Platform documentation in `data_models.md`
- Identity setup in `identity_config.md`
