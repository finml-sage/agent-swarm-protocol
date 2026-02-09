"""POST /swarm/message endpoint handler."""
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, status

from src.server.models.requests import MessageRequest
from src.server.models.responses import MessageQueuedResponse
from src.state.database import DatabaseManager
from src.state.models.inbox import InboxMessage, InboxStatus
from src.state.repositories.inbox import InboxRepository
from src.claude.wake_trigger import WakeTrigger

logger = logging.getLogger(__name__)


def create_message_router(db: DatabaseManager) -> APIRouter:
    """Create message router with injected dependencies."""
    router = APIRouter()

    @router.post(
        "/swarm/message",
        response_model=MessageQueuedResponse,
        status_code=status.HTTP_200_OK,
        tags=["messages"],
    )
    async def receive_message(
        request: Request, body: MessageRequest,
    ) -> MessageQueuedResponse:
        """Receive and persist a message from another agent.

        Idempotent: re-posting a message with the same message_id
        returns 'queued' without raising an error.

        After persistence, the wake trigger (if configured) evaluates
        whether to WAKE, QUEUE, or SKIP the message.
        """
        inbox_msg = InboxMessage(
            message_id=body.message_id,
            swarm_id=body.swarm_id,
            sender_id=body.sender.agent_id,
            recipient_id=body.recipient,
            message_type=body.type,
            content=body.model_dump_json(),
            received_at=datetime.now(timezone.utc),
            status=InboxStatus.UNREAD,
        )
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            try:
                await repo.insert(inbox_msg)
            except sqlite3.IntegrityError:
                logger.debug(
                    "Duplicate message %s ignored (idempotent)",
                    body.message_id,
                )

        # Fire-and-forget wake trigger evaluation (non-blocking).
        # Catch all exceptions: wake is a side effect that must never
        # prevent message acceptance (e.g. httpx.ReadTimeout, WakeTriggerError).
        wake_trigger: Optional[WakeTrigger] = getattr(
            request.app.state, "wake_trigger", None,
        )
        if wake_trigger is not None:
            try:
                event = await wake_trigger.process_message(inbox_msg)
                logger.info(
                    "Wake trigger: message=%s decision=%s",
                    body.message_id,
                    event.decision.value,
                )
            except Exception as exc:
                # Log but do not fail the message acceptance
                logger.warning(
                    "Wake trigger failed for message %s: %s",
                    body.message_id,
                    exc,
                )

        return MessageQueuedResponse(
            status="queued", message_id=body.message_id,
        )

    return router
