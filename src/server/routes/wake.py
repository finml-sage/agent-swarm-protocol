"""POST /api/wake endpoint for agent invocation."""
import logging
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Header, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.claude.session_manager import SessionManager, SessionState
from src.server.invoker import AgentInvoker

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


def create_wake_router(
    session_manager: SessionManager,
    invoker: AgentInvoker,
    wake_secret: str = "",
) -> APIRouter:
    """Create the /api/wake router with injected dependencies.

    Args:
        session_manager: Tracks whether an agent session is active.
        invoker: Pluggable agent invocation strategy.
        wake_secret: Shared secret for auth. Empty string disables auth.
    """
    router = APIRouter()

    @router.post(
        "/api/wake",
        response_model=WakeResponse,
        status_code=status.HTTP_200_OK,
        tags=["wake"],
    )
    async def wake_agent(
        request: Request,
        body: WakeRequest,
        x_wake_secret: Optional[str] = Header(default=None),
    ) -> WakeResponse | JSONResponse:
        """Invoke the agent in response to a wake trigger.

        Returns:
            - ``invoked``: agent was not active; invocation started.
            - ``already_active``: agent session is already running.
            - ``error``: invocation failed.
        """
        # Auth check: if a secret is configured, require it
        if wake_secret and x_wake_secret != wake_secret:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content=WakeResponse(
                    status="error", detail="Invalid or missing X-Wake-Secret header"
                ).model_dump(),
            )

        # Session check: avoid double-invocation
        session = session_manager.get_current_session()
        if session is not None and session.state == SessionState.ACTIVE:
            if session_manager.should_resume():
                logger.info(
                    "Agent already active (session=%s), skipping invocation",
                    session.session_id,
                )
                return WakeResponse(status="already_active")

        # Invoke the agent
        payload = body.model_dump()
        try:
            await invoker.invoke(payload)
        except Exception as exc:
            logger.error("Agent invocation failed: %s", exc)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content=WakeResponse(
                    status="error", detail=str(exc)
                ).model_dump(),
            )

        logger.info(
            "Agent invoked for message=%s swarm=%s",
            body.message_id,
            body.swarm_id,
        )
        return WakeResponse(status="invoked")

    return router
