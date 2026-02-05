"""POST /swarm/join endpoint handler."""
import logging
from typing import Union

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from src.server.config import ServerConfig
from src.server.models.common import Member
from src.server.models.requests import JoinRequest
from src.server.models.responses import (
    ErrorDetail,
    ErrorResponse,
    JoinAcceptedResponse,
    JoinPendingResponse,
)
from src.server.routes._join_helpers import extract_swarm_id, find_master_public_key
from src.state.database import DatabaseManager
from src.state.join import (
    ApprovalRequiredError,
    SwarmNotFoundError,
    lookup_swarm,
    validate_and_join,
)
from src.state.token import TokenExpiredError, TokenPayloadError, TokenSignatureError

logger = logging.getLogger(__name__)


def create_join_router(config: ServerConfig, db: DatabaseManager) -> APIRouter:
    """Create join router with injected dependencies."""
    router = APIRouter()

    @router.post(
        "/swarm/join",
        response_model=Union[JoinAcceptedResponse, JoinPendingResponse],
        status_code=status.HTTP_200_OK,
        tags=["membership"],
    )
    async def join_swarm(
        request: Request, body: JoinRequest,
    ) -> Union[JoinAcceptedResponse, JoinPendingResponse, JSONResponse]:
        """Handle a request to join a swarm.

        Idempotent: if the agent is already a member, returns 200 with
        current membership data instead of 409.
        """
        try:
            swarm_id = extract_swarm_id(body.invite_token)
        except TokenPayloadError as exc:
            return _error(400, "INVALID_TOKEN", str(exc))

        try:
            async with db.connection() as conn:
                swarm = await lookup_swarm(conn, swarm_id)
                master_key = find_master_public_key(swarm.members, swarm.master)
                result = await validate_and_join(
                    conn=conn,
                    invite_token=body.invite_token,
                    master_public_key=master_key,
                    agent_id=body.sender.agent_id,
                    agent_endpoint=body.sender.endpoint,
                    agent_public_key=body.sender.public_key,
                )
        except (TokenSignatureError, TokenExpiredError) as exc:
            logger.warning("Join rejected for '%s': %s", body.sender.agent_id, exc)
            return _error(401, "INVALID_SIGNATURE", str(exc))
        except TokenPayloadError as exc:
            return _error(400, "INVALID_TOKEN", str(exc))
        except SwarmNotFoundError as exc:
            return _error(404, "SWARM_NOT_FOUND", str(exc))
        except ApprovalRequiredError as exc:
            logger.info("Join pending for '%s' in '%s'", body.sender.agent_id, swarm_id)
            return JSONResponse(
                status_code=202,
                content=JoinPendingResponse(
                    status="pending", swarm_id=swarm_id, message=str(exc),
                ).model_dump(),
            )

        members = [
            Member(agent_id=m.agent_id, endpoint=m.endpoint, public_key=m.public_key)
            for m in result.members
        ]
        logger.info("Agent '%s' joined swarm '%s'", body.sender.agent_id, result.swarm_id)
        return JoinAcceptedResponse(
            status="accepted",
            swarm_id=result.swarm_id,
            swarm_name=result.swarm_name,
            members=members,
        )

    return router


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    """Build a structured JSON error response."""
    body = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status_code, content=body.model_dump())
