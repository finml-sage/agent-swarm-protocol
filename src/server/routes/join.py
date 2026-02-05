"""POST /swarm/join endpoint handler."""
from typing import Union
from fastapi import APIRouter, Request, status
from src.server.models.requests import JoinRequest
from src.server.models.responses import JoinAcceptedResponse, JoinPendingResponse


def create_join_router() -> APIRouter:
    """Create join router."""
    router = APIRouter()

    @router.post(
        "/swarm/join",
        response_model=Union[JoinAcceptedResponse, JoinPendingResponse],
        status_code=status.HTTP_202_ACCEPTED,
        tags=["membership"],
    )
    async def join_swarm(request: Request, body: JoinRequest) -> Union[JoinAcceptedResponse, JoinPendingResponse]:
        """Handle a request to join a swarm."""
        return JoinPendingResponse(
            status="pending",
            swarm_id="00000000-0000-0000-0000-000000000000",
            message="Join request requires master approval",
        )

    return router
