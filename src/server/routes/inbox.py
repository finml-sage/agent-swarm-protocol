"""Inbox API endpoints for managing received messages.

Endpoints expose the inbox table with status management: unread, read,
archived, and soft-delete. Replaces the old /api/messages endpoints.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Path, Query, status
from fastapi.responses import JSONResponse

from src.server.models.inbox import (
    InboxBatchRequest,
    InboxBatchResponse,
    InboxCountResponse,
    InboxListResponse,
    InboxMessageResponse,
    InboxStatusResponse,
)
from src.server.routes._inbox_helpers import msg_to_response
from src.state.database import DatabaseManager
from src.state.models.inbox import InboxStatus
from src.state.repositories.inbox import InboxRepository

logger = logging.getLogger(__name__)

_VALID_STATUSES = frozenset({"unread", "read", "archived", "all"})
_ACTION_MAP = {"read": InboxStatus.READ, "archive": InboxStatus.ARCHIVED, "delete": InboxStatus.DELETED}


def create_inbox_router(db: DatabaseManager) -> APIRouter:
    """Create the inbox router with injected database dependency."""
    router = APIRouter()

    @router.get("/api/inbox", response_model=InboxListResponse, tags=["inbox"])
    async def list_messages(
        status_filter: Annotated[str, Query(alias="status", description="unread|read|archived|all")] = "unread",
        swarm_id: Annotated[str | None, Query(description="Swarm ID filter")] = None,
        sender_id: Annotated[str | None, Query(description="Sender ID filter")] = None,
        limit: Annotated[int, Query(ge=1, le=100, description="Max messages")] = 20,
    ) -> InboxListResponse | JSONResponse:
        """List inbox messages, defaults to unread only."""
        if status_filter not in _VALID_STATUSES:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": f"Invalid status '{status_filter}'. Valid: {', '.join(sorted(_VALID_STATUSES))}"},
            )
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            messages = await repo.list_visible(status_filter, swarm_id, sender_id, limit)
        items = [msg_to_response(m) for m in messages]
        return InboxListResponse(count=len(items), messages=items)

    @router.get("/api/inbox/count", response_model=InboxCountResponse, tags=["inbox"])
    async def inbox_count(
        swarm_id: Annotated[str | None, Query(description="Swarm ID filter")] = None,
    ) -> InboxCountResponse:
        """Count inbox messages by status, optionally filtered by swarm."""
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            counts = await repo.count_by_status(swarm_id)
        return InboxCountResponse(
            unread=counts.get("unread", 0), read=counts.get("read", 0),
            archived=counts.get("archived", 0), deleted=counts.get("deleted", 0),
            total=counts.get("total", 0),
        )

    @router.get("/api/inbox/{message_id}", response_model=InboxMessageResponse, tags=["inbox"])
    async def get_message(
        message_id: Annotated[str, Path(description="Message ID")],
    ) -> InboxMessageResponse | JSONResponse:
        """Get a single message. Auto-marks as read if unread."""
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            msg = await repo.get_by_id(message_id)
            if msg is None:
                return JSONResponse(status_code=404, content={"error": f"Message {message_id} not found"})
            if msg.status == InboxStatus.UNREAD:
                await repo.mark_read(message_id)
                msg = await repo.get_by_id(message_id)
        return msg_to_response(msg)  # type: ignore[arg-type]

    @router.post("/api/inbox/{message_id}/read", response_model=InboxStatusResponse, tags=["inbox"])
    async def mark_read(
        message_id: Annotated[str, Path(description="Message ID")],
    ) -> InboxStatusResponse | JSONResponse:
        """Explicitly mark a message as read (idempotent)."""
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            msg = await repo.get_by_id(message_id)
            if msg is None:
                return JSONResponse(status_code=404, content={"error": f"Message {message_id} not found"})
            await repo.mark_read(message_id)
        return InboxStatusResponse(status="read", message_id=message_id)

    @router.post("/api/inbox/{message_id}/archive", response_model=InboxStatusResponse, tags=["inbox"])
    async def archive_message(
        message_id: Annotated[str, Path(description="Message ID")],
    ) -> InboxStatusResponse | JSONResponse:
        """Archive a message."""
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            msg = await repo.get_by_id(message_id)
            if msg is None:
                return JSONResponse(status_code=404, content={"error": f"Message {message_id} not found"})
            updated = await repo.mark_archived(message_id)
            if not updated:
                return JSONResponse(status_code=400, content={"error": f"Cannot archive from '{msg.status.value}'"})
        return InboxStatusResponse(status="archived", message_id=message_id)

    @router.post("/api/inbox/{message_id}/delete", response_model=InboxStatusResponse, tags=["inbox"])
    async def delete_message(
        message_id: Annotated[str, Path(description="Message ID")],
    ) -> InboxStatusResponse | JSONResponse:
        """Soft-delete a message."""
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            msg = await repo.get_by_id(message_id)
            if msg is None:
                return JSONResponse(status_code=404, content={"error": f"Message {message_id} not found"})
            await repo.mark_deleted(message_id)
        logger.info("Message %s soft-deleted via inbox API", message_id)
        return InboxStatusResponse(status="deleted", message_id=message_id)

    @router.post("/api/inbox/batch", response_model=InboxBatchResponse, tags=["inbox"])
    async def batch_action(body: InboxBatchRequest) -> InboxBatchResponse | JSONResponse:
        """Batch status update for multiple messages."""
        target_status = _ACTION_MAP.get(body.action)
        if target_status is None:
            return JSONResponse(status_code=400, content={"error": f"Invalid action '{body.action}'"})
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            updated = await repo.batch_update_status(body.message_ids, target_status)
        return InboxBatchResponse(action=body.action, updated=updated, total=len(body.message_ids))

    return router
