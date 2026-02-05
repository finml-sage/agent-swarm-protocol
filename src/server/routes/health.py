"""GET /swarm/health endpoint handler."""
from datetime import datetime, timezone
from fastapi import APIRouter, status
from src.server.config import ServerConfig
from src.server.models.responses import HealthResponse
from src.server.queue import MessageQueue

QUEUE_BACKLOG_THRESHOLD = 0.8


def create_health_router(config: ServerConfig, queue: MessageQueue) -> APIRouter:
    """Create health router with injected dependencies."""
    router = APIRouter()

    @router.get("/swarm/health", response_model=HealthResponse, status_code=status.HTTP_200_OK, tags=["status"])
    async def health_check() -> HealthResponse:
        """Check if the agent is operational."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        queue_fill_ratio = queue.size() / config.queue_max_size
        if queue_fill_ratio >= QUEUE_BACKLOG_THRESHOLD:
            return HealthResponse(
                status="degraded", agent_id=config.agent.agent_id,
                protocol_version=config.agent.protocol_version, timestamp=timestamp,
                message="Message queue backlog exceeds threshold",
            )
        return HealthResponse(
            status="healthy", agent_id=config.agent.agent_id,
            protocol_version=config.agent.protocol_version, timestamp=timestamp,
        )

    return router
