"""POST /swarm/join endpoint handler."""
import logging
from datetime import datetime, timezone
from typing import Optional, Union

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from src.server.broadcast import broadcast_member_joined
from src.server.config import ServerConfig
from src.server.models.common import Member
from src.server.models.requests import JoinRequest
from src.server.models.responses import (
    ErrorDetail,
    ErrorResponse,
    JoinAcceptedResponse,
    JoinPendingResponse,
)
from src.server.notifications import notify_member_joined
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


def _load_master_private_key(config: ServerConfig) -> Optional[Ed25519PrivateKey]:
    """Load the master's Ed25519 private key from disk.

    Returns None (and logs a warning) when the path is missing or the
    file cannot be read. Callers MUST treat None as "skip broadcast" —
    the local notification still persists, only the cross-host fan-out
    is degraded.
    """
    path = config.agent.private_key_path
    if path is None:
        return None
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        return Ed25519PrivateKey.from_private_bytes(raw)
    except (OSError, ValueError) as exc:
        logger.warning(
            "Failed to load master private key from %s: %s. "
            "member_joined broadcast will be skipped.",
            path, exc,
        )
        return None


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

        On a genuinely new join, a member_joined system notification is
        persisted to the message queue (fire-and-forget).
        """
        try:
            swarm_id = extract_swarm_id(body.invite_token)
        except TokenPayloadError as exc:
            return _error(400, "INVALID_TOKEN", str(exc))

        try:
            async with db.connection() as conn:
                swarm = await lookup_swarm(conn, swarm_id)
                was_member = any(
                    m.agent_id == body.sender.agent_id for m in swarm.members
                )
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

        # Fire-and-forget: persist + broadcast only for genuinely new joins.
        # Both side effects are best-effort: a notification or broadcast
        # failure must never reverse a successful join.
        if not was_member:
            new_member = next(
                (m for m in result.members if m.agent_id == body.sender.agent_id),
                None,
            )
            joined_at_dt = (
                new_member.joined_at if new_member is not None
                else datetime.now(timezone.utc)
            )
            joined_at_iso = (
                joined_at_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            )

            try:
                await notify_member_joined(
                    db,
                    swarm_id=result.swarm_id,
                    agent_id=body.sender.agent_id,
                    endpoint=body.sender.endpoint,
                    joined_at=joined_at_iso,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to persist join notification for '%s': %s",
                    body.sender.agent_id,
                    exc,
                )

            # Cross-host fan-out (#200): inform every existing member so
            # PR #198's receiver dispatcher can write the new agent into
            # their local swarm_members table. Wrap the entire call in
            # try/except as belt-and-suspenders — broadcast.py already
            # swallows per-member failures, but a config or signing-time
            # error must not block join acceptance.
            master_private_key = _load_master_private_key(config)
            if master_private_key is not None:
                try:
                    await broadcast_member_joined(
                        members=result.members,
                        new_agent_id=body.sender.agent_id,
                        swarm_id=result.swarm_id,
                        master_id=config.agent.agent_id,
                        master_endpoint=config.agent.endpoint,
                        master_private_key=master_private_key,
                        new_agent_endpoint=body.sender.endpoint,
                        joined_at=joined_at_dt,
                    )
                except Exception as exc:
                    logger.warning(
                        "member_joined broadcast for '%s' failed: %s",
                        body.sender.agent_id, exc,
                    )
            else:
                logger.info(
                    "member_joined broadcast skipped for '%s': "
                    "AGENT_PRIVATE_KEY_PATH not configured",
                    body.sender.agent_id,
                )

        members = [
            Member(agent_id=m.agent_id, endpoint=m.endpoint, public_key=m.public_key)
            for m in result.members
        ]
        logger.info(
            "Agent '%s' joined swarm '%s'", body.sender.agent_id, result.swarm_id,
        )
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
