"""GET /swarm/info endpoint handler."""
from typing import Optional
from fastapi import APIRouter, status
from src.server.config import ServerConfig
from src.server.models.responses import AgentInfoResponse


def create_info_router(config: ServerConfig) -> APIRouter:
    """Create info router with injected dependencies."""
    router = APIRouter()

    @router.get("/swarm/info", response_model=AgentInfoResponse, status_code=status.HTTP_200_OK, tags=["status"])
    async def agent_info() -> AgentInfoResponse:
        """Get public information about this agent."""
        metadata: Optional[dict[str, str]] = None
        if config.agent.name or config.agent.description:
            metadata = {}
            if config.agent.name:
                metadata["name"] = config.agent.name
            if config.agent.description:
                metadata["description"] = config.agent.description
        return AgentInfoResponse(
            agent_id=config.agent.agent_id, endpoint=config.agent.endpoint,
            public_key=config.agent.public_key, protocol_version=config.agent.protocol_version,
            capabilities=list(config.agent.capabilities), metadata=metadata,
        )

    return router
