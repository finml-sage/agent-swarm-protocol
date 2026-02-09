"""Outbox API endpoints for listing sent messages."""

import logging
from typing import Annotated

from fastapi import APIRouter, Query, status

from src.server.models.inbox import (
    OutboxCountResponse,
    OutboxListResponse,
    OutboxMessageResponse,
)
from src.state.database import DatabaseManager
from src.state.repositories.outbox import OutboxRepository

logger = logging.getLogger(__name__)


def create_outbox_router(db: DatabaseManager) -> APIRouter:
    """Create the outbox router with injected database dependency."""
    router = APIRouter()

    @router.get(
        "/api/outbox",
        response_model=OutboxListResponse,
        status_code=status.HTTP_200_OK,
        tags=["outbox"],
    )
    async def list_sent(
        swarm_id: Annotated[str | None, Query(description="Swarm ID filter")] = None,
        limit: Annotated[int, Query(ge=1, le=100, description="Max messages")] = 20,
    ) -> OutboxListResponse:
        """List sent messages from the outbox."""
        async with db.connection() as conn:
            repo = OutboxRepository(conn)
            if swarm_id:
                messages = await repo.list_by_swarm(swarm_id, limit=limit)
            else:
                messages = await repo.list_all(limit=limit)

        items = [
            OutboxMessageResponse(
                message_id=m.message_id,
                swarm_id=m.swarm_id,
                recipient_id=m.recipient_id,
                message_type=m.message_type,
                status=m.status.value,
                sent_at=m.sent_at.isoformat(),
                error=m.error,
                content_preview=m.content[:200],
            )
            for m in messages
        ]
        return OutboxListResponse(count=len(items), messages=items)

    @router.get(
        "/api/outbox/count",
        response_model=OutboxCountResponse,
        status_code=status.HTTP_200_OK,
        tags=["outbox"],
    )
    async def outbox_count(
        swarm_id: Annotated[str, Query(description="Swarm ID to query")],
    ) -> OutboxCountResponse:
        """Count outbox messages by status for a swarm."""
        async with db.connection() as conn:
            repo = OutboxRepository(conn)
            counts = await repo.count_by_swarm(swarm_id)
        return OutboxCountResponse(
            sent=counts.get("sent", 0),
            delivered=counts.get("delivered", 0),
            failed=counts.get("failed", 0),
            total=counts.get("total", 0),
        )

    return router
