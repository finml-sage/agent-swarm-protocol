"""POST /api/wake endpoint for agent invocation."""
import asyncio
import logging
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Header, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.claude.session_manager import SessionManager, SessionState
from src.server.invoker import AgentInvoker
from src.state.database import DatabaseManager
from src.state.session_service import lookup_sdk_session, persist_sdk_session

logger = logging.getLogger(__name__)


class WakeRequest(BaseModel):
    """Payload POSTed by WakeTrigger to invoke the agent."""

    message_id: Annotated[str, Field(description="ID of the triggering message")]
    swarm_id: Annotated[str, Field(description="Swarm the message belongs to")]
    sender_id: Annotated[str, Field(description="Agent that sent the message")]
    notification_level: Annotated[str, Field(description="Wake urgency level")]


class WakeResponse(BaseModel):
    """Response from the wake endpoint."""

    status: Annotated[
        Literal["invoked", "already_active", "error"],
        Field(description="Outcome of the wake request"),
    ]
    detail: Optional[str] = None


# Module-level lock prevents concurrent SDK invocations (~450MB each).
_invoke_lock = asyncio.Lock()


def create_wake_router(
    session_manager: SessionManager,
    invoker: AgentInvoker,
    wake_secret: str = "",
    db_manager: Optional[DatabaseManager] = None,
    session_timeout_minutes: int = 30,
) -> APIRouter:
    """Create the /api/wake router with injected dependencies.

    Args:
        session_manager: Tracks whether an agent session is active.
        invoker: Pluggable agent invocation strategy.
        wake_secret: Shared secret for auth. Empty string disables auth.
        db_manager: Database manager for SDK session persistence.
        session_timeout_minutes: Idle timeout before starting fresh session.
    """
    router = APIRouter()

    async def _invoke_background(
        payload: dict,
        resume_id: Optional[str],
        swarm_id: str,
        sender_id: str,
        message_id: str,
    ) -> None:
        """Run agent invocation and session persistence in the background.

        Acquires the module-level lock to prevent multiple simultaneous
        SDK invocations (each is ~450MB of memory).
        """
        if _invoke_lock.locked():
            logger.warning(
                "Skipping invocation for message=%s: another invocation in progress",
                message_id,
            )
            return

        async with _invoke_lock:
            try:
                new_session_id = await invoker.invoke(payload, resume=resume_id)
            except Exception as exc:
                logger.error("Background agent invocation failed: %s", exc)
                return

            if db_manager is not None and new_session_id is not None:
                await persist_sdk_session(
                    db_manager, swarm_id, sender_id, new_session_id,
                )

            logger.info(
                "Background invocation complete for message=%s swarm=%s session=%s",
                message_id, swarm_id, new_session_id,
            )

    @router.post(
        "/api/wake",
        response_model=WakeResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["wake"],
    )
    async def wake_agent(
        request: Request,
        body: WakeRequest,
        x_wake_secret: Optional[str] = Header(default=None),
    ) -> WakeResponse | JSONResponse:
        """Invoke the agent in response to a wake trigger.

        Returns 202 Accepted immediately and runs the invocation in
        a background task.  An asyncio.Lock prevents multiple
        simultaneous SDK invocations.
        """
        # Auth check
        if wake_secret and x_wake_secret != wake_secret:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content=WakeResponse(
                    status="error", detail="Invalid or missing X-Wake-Secret header"
                ).model_dump(),
            )

        # Session check: avoid double-invocation (returns 200, not 202)
        session = session_manager.get_current_session()
        if session is not None and session.state == SessionState.ACTIVE:
            if session_manager.should_resume():
                logger.info(
                    "Agent already active (session=%s), skipping",
                    session.session_id,
                )
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content=WakeResponse(status="already_active").model_dump(),
                )

        # Look up previous SDK session for conversation continuity
        resume_id: Optional[str] = None
        if db_manager is not None:
            resume_id = await lookup_sdk_session(
                db_manager, body.swarm_id, body.sender_id,
                session_timeout_minutes,
            )

        # Fire-and-forget: launch invocation in background task
        payload = body.model_dump()
        asyncio.create_task(
            _invoke_background(
                payload, resume_id,
                body.swarm_id, body.sender_id, body.message_id,
            )
        )

        logger.info(
            "Wake accepted for message=%s swarm=%s (background)",
            body.message_id, body.swarm_id,
        )
        return WakeResponse(status="invoked")

    return router
