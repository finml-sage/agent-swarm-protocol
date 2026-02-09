"""Inbox API endpoints for listing and managing server-side messages.

These endpoints expose the server's message_queue (the real inbox) to
CLI clients and external consumers.  Prior to this, the CLI read from
the client-side DB (~/.swarm/swarm.db) which contains zero inbound
messages -- see issue #151.
"""

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Path, Query, status
from fastapi.responses import JSONResponse

from src.server.models.inbox import (
    InboxAckResponse,
    InboxCountResponse,
    InboxListResponse,
    InboxMessage,
)
from src.state.database import DatabaseManager
from src.state.models.message import MessageStatus
from src.state.repositories.messages import MessageRepository

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Valid status filter values
# ---------------------------------------------------------------------------

_VALID_STATUSES = frozenset({"pending", "completed", "failed", "all"})


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_inbox_router(db: DatabaseManager) -> APIRouter:
    """Create the inbox router with injected database dependency.

    Endpoints:
        GET  /api/messages              - List messages
        GET  /api/messages/count        - Count messages by status
        POST /api/messages/{id}/ack     - Mark a message as completed
    """
    router = APIRouter()

    @router.get(
        "/api/messages",
        response_model=InboxListResponse,
        status_code=status.HTTP_200_OK,
        tags=["inbox"],
    )
    async def list_messages(
        swarm_id: Annotated[str, Query(description="Swarm ID to query")],
        status_filter: Annotated[
            str,
            Query(alias="status", description="Filter: pending|completed|failed|all"),
        ] = "pending",
        limit: Annotated[
            int,
            Query(ge=1, le=100, description="Max messages to return"),
        ] = 20,
    ) -> InboxListResponse | JSONResponse:
        """List messages from the server message queue."""
        if status_filter not in _VALID_STATUSES:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "error": f"Invalid status '{status_filter}'. "
                    f"Valid values: {', '.join(sorted(_VALID_STATUSES))}",
                },
            )

        ms: Optional[MessageStatus] = None
        if status_filter != "all":
            ms = MessageStatus(status_filter)

        async with db.connection() as conn:
            repo = MessageRepository(conn)
            messages = await repo.list_by_status(swarm_id, status=ms, limit=limit)

        items = [
            InboxMessage(
                message_id=m.message_id,
                swarm_id=m.swarm_id,
                sender_id=m.sender_id,
                message_type=m.message_type,
                status=m.status.value,
                received_at=m.received_at.isoformat(),
                content_preview=m.content[:200],
            )
            for m in messages
        ]

        return InboxListResponse(count=len(items), messages=items)

    @router.get(
        "/api/messages/count",
        response_model=InboxCountResponse,
        status_code=status.HTTP_200_OK,
        tags=["inbox"],
    )
    async def message_count(
        swarm_id: Annotated[str, Query(description="Swarm ID to query")],
    ) -> InboxCountResponse:
        """Count messages by status for a swarm."""
        async with db.connection() as conn:
            repo = MessageRepository(conn)
            counts = await repo.count_by_status(swarm_id)

        return InboxCountResponse(
            pending=counts["pending"],
            completed=counts["completed"],
            failed=counts["failed"],
            total=counts["total"],
        )

    @router.post(
        "/api/messages/{message_id}/ack",
        response_model=InboxAckResponse,
        status_code=status.HTTP_200_OK,
        responses={404: {"model": InboxAckResponse}},
        tags=["inbox"],
    )
    async def ack_message(
        message_id: Annotated[str, Path(description="Message ID to acknowledge")],
    ) -> InboxAckResponse | JSONResponse:
        """Mark a message as completed (acknowledged)."""
        async with db.connection() as conn:
            repo = MessageRepository(conn)
            found = await repo.complete(message_id)

        if found:
            logger.info("Message %s acknowledged via inbox API", message_id)
            return InboxAckResponse(status="acked", message_id=message_id)

        logger.warning("Ack request for unknown message %s", message_id)
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=InboxAckResponse(
                status="not_found", message_id=message_id,
            ).model_dump(),
        )

    return router
