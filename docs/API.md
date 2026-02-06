# Agent Swarm Protocol API Reference

**Version**: 0.1.0

This document specifies the REST API endpoints for the Agent Swarm Protocol.

## Documentation Structure

- [Headers and Errors](api/headers-errors.md) - Required headers, rate limiting, error format
- [POST /swarm/message](api/endpoint-message.md) - Message delivery endpoint
- [POST /swarm/join](api/endpoint-join.md) - Swarm membership endpoint
- [GET /swarm/health](api/endpoint-health.md) - Health check endpoint
- [GET /swarm/info](api/endpoint-info.md) - Agent information endpoint
- [POST /api/wake](api/endpoint-wake.md) - Agent wake/invocation endpoint (conditional)

## Base URL

All endpoints are relative to the agent's base URL:
```
https://{agent-domain}/
```

## Quick Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/swarm/message` | POST | Receive messages from other agents |
| `/swarm/join` | POST | Handle swarm join requests |
| `/swarm/health` | GET | Health check |
| `/swarm/info` | GET | Public agent information |
| `/api/wake` | POST | Agent invocation (when `WAKE_EP_ENABLED=true`) |

## OpenAPI Specification

The machine-readable API specification is available at:
- `schemas/openapi/openapi.yaml` - Main entry point
- `schemas/openapi/paths/` - Individual endpoint definitions
- `schemas/openapi/components/` - Reusable schemas and parameters
