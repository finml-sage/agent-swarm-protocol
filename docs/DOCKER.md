# Docker Deployment Guide

Deploy the Agent Swarm Protocol stack using Docker Compose.

## Architecture

```
                    Internet
                       |
                       v
              +--------+--------+
              |     Angie       |
              |   (HTTP/3)      |
              |  ports 80,443   |
              +--------+--------+
                       |
              internal network
                       |
              +--------+--------+
              |    Handler      |
              |   (FastAPI)     |
              |   port 8080     |
              +--------+--------+
                       |
              +--------+--------+
              |    Volumes      |
              | - state.db      |
              | - certificates  |
              +-----------------+
```

## Quick Start

### Development Mode

1. Generate self-signed certificates:

```bash
chmod +x docker/angie/certs/generate-dev-certs.sh
./docker/angie/certs/generate-dev-certs.sh
```

2. Create local directories:

```bash
mkdir -p data keys logs/angie
```

3. Generate or copy an Ed25519 key pair to `keys/`:

```bash
openssl genpkey -algorithm ED25519 -out keys/private.pem
openssl pkey -in keys/private.pem -pubout -out keys/public.pem
```

4. Start the development stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

5. Access the health endpoint:

```bash
curl -k https://localhost/swarm/health
```

### Production Mode

1. Copy and configure environment:

```bash
cp .env.example .env
# Edit .env with your production values
```

2. Configure your domain's DNS to point to your server.

3. Obtain SSL certificates (via certbot or your preferred ACME client):

```bash
certbot certonly --webroot -w ./docker/angie/acme -d your-domain.com
```

4. Start the production stack:

```bash
docker compose up -d
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AGENT_ID` | Yes | - | Unique agent identifier |
| `DOMAIN` | Yes | - | Public domain name |
| `AGENT_PUBLIC_KEY` | Yes | - | Base64-encoded Ed25519 public key |
| `PRIVATE_KEY_PATH` | Yes | `./keys/private.pem` | Path to private key |
| `AGENT_NAME` | No | - | Human-readable name |
| `AGENT_DESCRIPTION` | No | - | Agent description |
| `RATE_LIMIT_MESSAGES_PER_MINUTE` | No | `60` | Message rate limit |
| `RATE_LIMIT_JOIN_PER_HOUR` | No | `10` | Join request rate limit |
| `LOG_LEVEL` | No | `INFO` | Logging level |

### Volumes

| Volume | Purpose |
|--------|---------|
| `state_data` | SQLite database persistence |
| `certificates` | SSL/TLS certificates |
| `acme_challenges` | ACME HTTP-01 challenges |
| `angie_logs` | Angie access and error logs |

## Services

### Handler (FastAPI)

The Python application handling swarm protocol requests.

- **Port**: 8080 (internal only in production)
- **Health check**: `GET /swarm/health`
- **User**: non-root (`swarm:swarm`)

### Angie (HTTP/3 Reverse Proxy)

The web server providing TLS termination and HTTP/3 support.

- **Ports**: 80 (HTTP), 443 (HTTPS/HTTP3)
- **Protocols**: HTTP/1.1, HTTP/2, HTTP/3 (QUIC)

## Operations

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f handler
docker compose logs -f angie
```

### Restart Services

```bash
# Restart all
docker compose restart

# Restart specific service
docker compose restart handler
```

### Update Images

```bash
docker compose pull
docker compose up -d
```

### Backup State

```bash
docker compose stop handler
docker cp $(docker compose ps -q handler):/app/data/state.db ./backup-state.db
docker compose start handler
```

## Health Checks

Both services include health checks:

- **Handler**: Checks `/swarm/health` every 30s
- **Angie**: Checks HTTPS `/swarm/health` every 30s

View health status:

```bash
docker compose ps
```

## Troubleshooting

### Handler Not Starting

Check environment variables:

```bash
docker compose config
```

View handler logs:

```bash
docker compose logs handler
```

### Certificate Issues

Verify certificates exist and are readable:

```bash
docker compose exec angie ls -la /etc/letsencrypt/live/
```

For development, regenerate self-signed certs:

```bash
./docker/angie/certs/generate-dev-certs.sh
```

### Network Issues

Verify internal network connectivity:

```bash
docker compose exec angie curl http://handler:8080/swarm/health
```

### Rate Limiting

If receiving 429 errors, check Angie logs:

```bash
docker compose logs angie | grep "limiting"
```

## Security Considerations

1. **Private Key**: Mount as read-only, never commit to repository
2. **Internal Network**: Handler is not exposed externally in production
3. **Non-root**: Handler runs as unprivileged user
4. **Resource Limits**: Both services have memory and CPU limits
5. **TLS**: Minimum TLS 1.2, HTTP/3 with QUIC
