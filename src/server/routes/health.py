"""GET /swarm/health endpoint handler."""
from datetime import datetime, timezone
from fastapi import APIRouter, status
from src.server.config import ServerConfig
from src.server.models.responses import HealthResponse


def create_health_router(config: ServerConfig) -> APIRouter:
    """Create health router with injected dependencies."""
    router = APIRouter()

    @router.get("/swarm/health", response_model=HealthResponse, status_code=status.HTTP_200_OK, tags=["status"])
    async def health_check() -> HealthResponse:
        """Check if the agent is operational."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        return HealthResponse(
            status="healthy", agent_id=config.agent.agent_id,
            protocol_version=config.agent.protocol_version, timestamp=timestamp,
        )

    return router
