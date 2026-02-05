"""POST /swarm/message endpoint handler."""
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Union

from fastapi import APIRouter, Request, status

from src.server.models.requests import MessageRequest
from src.server.models.responses import MessageQueuedResponse, MessageResponse
from src.server.queue import MessageQueue
from src.state.database import DatabaseManager
from src.state.models.message import QueuedMessage
from src.state.repositories.messages import MessageRepository

logger = logging.getLogger(__name__)


def create_message_router(
    queue: MessageQueue, db: DatabaseManager,
) -> APIRouter:
    """Create message router with injected dependencies."""
    router = APIRouter()

    @router.post(
        "/swarm/message",
        response_model=Union[MessageResponse, MessageQueuedResponse],
        status_code=status.HTTP_200_OK,
        tags=["messages"],
    )
    async def receive_message(
        request: Request, body: MessageRequest,
    ) -> Union[MessageResponse, MessageQueuedResponse]:
        """Receive and persist a message from another agent.

        Idempotent: re-posting a message with the same message_id
        returns 'queued' without raising an error.
        """
        message = QueuedMessage(
            message_id=body.message_id,
            swarm_id=body.swarm_id,
            sender_id=body.sender.agent_id,
            message_type=body.type,
            content=body.model_dump_json(),
            received_at=datetime.now(timezone.utc),
        )
        async with db.connection() as conn:
            repo = MessageRepository(conn)
            try:
                await repo.enqueue(message)
            except sqlite3.IntegrityError:
                logger.debug(
                    "Duplicate message %s ignored (idempotent)",
                    body.message_id,
                )
        await queue.put(body)
        return MessageQueuedResponse(
            status="queued", message_id=body.message_id,
        )

    return router
