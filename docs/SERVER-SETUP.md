# Server Setup Guide

This guide covers deploying an Agent Swarm Protocol agent with Angie (HTTP/3) and automatic TLS certificates.

## Prerequisites

- Ubuntu 22.04+ or Debian 12+
- Domain name with DNS pointing to your server
- Python 3.10+
- Root or sudo access

## Installation

### 1. Install Angie

```bash
# Add Angie repository
curl -fsSL https://angie.software/keys/angie-signing.gpg | \
    gpg --dearmor -o /usr/share/keyrings/angie-archive-keyring.gpg

echo "deb [signed-by=/usr/share/keyrings/angie-archive-keyring.gpg] \
    https://download.angie.software/angie/$(. /etc/os-release && echo $ID)/ \
    $(. /etc/os-release && echo $VERSION_CODENAME) main" | \
    sudo tee /etc/apt/sources.list.d/angie.list

sudo apt update
sudo apt install angie angie-module-http-v3
```

### 2. Install Certbot

```bash
sudo apt install certbot
```

### 3. Create ACME Challenge Directory

```bash
sudo mkdir -p /var/www/acme/.well-known/acme-challenge
sudo chown -R www-data:www-data /var/www/acme
```

## Configuration

### Template Variables

The Angie configuration template uses these variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `{{DOMAIN}}` | Your agent's fully qualified domain name | `agent.example.com` |
| `{{UPSTREAM_PORT}}` | Port where FastAPI runs | `8080` |
| `{{ACME_EMAIL}}` | Email for Let's Encrypt notifications | `admin@example.com` |

### Configuration Files

The configuration is modular:

| File | Purpose |
|------|---------|
| `angie.conf.template` | Main configuration with rate limiting and routing |
| `ssl.conf` | TLS 1.2/1.3 and QUIC settings |
| `security.conf` | Security headers (HSTS, X-Frame-Options, etc.) |
| `proxy_params.conf` | Upstream proxy settings |

### Generate Configuration

```bash
# Copy main template
cp src/server/angie.conf.template /etc/angie/angie.conf

# Replace template variables
sed -i 's/{{DOMAIN}}/agent.example.com/g' /etc/angie/angie.conf
sed -i 's/{{UPSTREAM_PORT}}/8080/g' /etc/angie/angie.conf

# Copy include files
sudo mkdir -p /etc/angie/conf.d
cp src/server/ssl.conf /etc/angie/conf.d/
cp src/server/security.conf /etc/angie/conf.d/
cp src/server/proxy_params.conf /etc/angie/conf.d/
```

### Obtain TLS Certificate

Before starting the full server, get your initial certificate:

```bash
# Start minimal HTTP server for ACME challenge
sudo angie -c /etc/angie/angie.conf

# Obtain certificate
sudo certbot certonly --webroot \
    -w /var/www/acme \
    -d agent.example.com \
    --email admin@example.com \
    --agree-tos \
    --non-interactive

# Verify certificate
sudo ls -la /etc/letsencrypt/live/agent.example.com/
```

### Enable ACME Auto-Renewal

```bash
# Test renewal
sudo certbot renew --dry-run

# Certbot installs a systemd timer automatically
sudo systemctl status certbot.timer
```

Create a post-renewal hook to reload Angie:

```bash
sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-angie.sh << 'EOF'
#!/bin/bash
systemctl reload angie
EOF

sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-angie.sh
```

## Starting the Server

### Start FastAPI Backend

```bash
cd /path/to/agent-swarm-protocol
python -m uvicorn src.server.main:app --host 127.0.0.1 --port 8080
```

Or with systemd:

```bash
sudo tee /etc/systemd/system/swarm-agent.service << EOF
[Unit]
Description=Agent Swarm Protocol Backend
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/agent-swarm-protocol
ExecStart=/usr/bin/python3 -m uvicorn src.server.main:app --host 127.0.0.1 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable swarm-agent
sudo systemctl start swarm-agent
```

### Start Angie

```bash
# Test configuration
sudo angie -t

# Start Angie
sudo systemctl start angie
sudo systemctl enable angie
```

## Verification

### Check HTTP/3 Support

```bash
# Using curl with HTTP/3 (requires curl 7.66+)
curl --http3 -I https://agent.example.com/swarm/health

# Check Alt-Svc header
curl -I https://agent.example.com/swarm/health | grep -i alt-svc
```

### Check TLS Configuration

```bash
# Using openssl
openssl s_client -connect agent.example.com:443 -tls1_3

# Using testssl.sh (optional)
./testssl.sh agent.example.com
```

### Test Endpoints

```bash
# Health check
curl https://agent.example.com/swarm/health

# Agent info
curl -H "X-Agent-ID: test" -H "X-Swarm-Protocol: 0.1.0" \
    https://agent.example.com/swarm/info
```

## Rate Limits

The configuration implements these rate limits:

| Endpoint | Limit | Burst |
|----------|-------|-------|
| `/swarm/message` | 60/minute per agent | 10 |
| `/swarm/join` | 10/hour per IP | 2 |
| `/swarm/info` | 100/minute per agent | 5 |
| `/swarm/health` | No limit | - |

Rate limit responses return HTTP 429 with headers:
- `X-RateLimit-Limit`
- `X-RateLimit-Remaining`
- `X-RateLimit-Reset`

## Security Headers

The configuration sets these security headers:

| Header | Value |
|--------|-------|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` |
| `X-Frame-Options` | `DENY` |
| `X-Content-Type-Options` | `nosniff` |
| `X-XSS-Protection` | `1; mode=block` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |

## Logging

Logs are written to:
- Access log: `/var/log/angie/access.log`
- Error log: `/var/log/angie/error.log`

The access log includes:
- Client IP
- Request details
- Response status
- `X-Agent-ID` header
- Timing information (request time, upstream times)

## Troubleshooting

### Certificate Issues

```bash
# Check certificate expiry
sudo certbot certificates

# Force renewal
sudo certbot renew --force-renewal

# Check Let's Encrypt logs
sudo journalctl -u certbot
```

### Connection Issues

```bash
# Check Angie status
sudo systemctl status angie

# Check for port conflicts
sudo ss -tlnp | grep -E ':(80|443)'

# Check error logs
sudo tail -f /var/log/angie/error.log
```

### HTTP/3 Not Working

1. Ensure UDP port 443 is open in firewall
2. Verify QUIC module is loaded
3. Check client supports HTTP/3 (curl 7.66+, Chrome/Firefox)

```bash
# Check firewall
sudo ufw status
sudo ufw allow 443/udp

# Verify module
angie -V 2>&1 | grep http_v3
```
