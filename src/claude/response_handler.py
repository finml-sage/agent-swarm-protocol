"""Response handler for sending Claude subagent replies via client."""
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from uuid import UUID

from src.client import SwarmClient
from src.client.types import MessageType, Priority
from src.state import DatabaseManager, MessageRepository


class ResponseAction(Enum):
    """Actions the Claude subagent can take."""
    REPLY = "reply"
    REPLY_DIRECT = "reply_direct"
    MUTE_AGENT = "mute_agent"
    MUTE_SWARM = "mute_swarm"
    LEAVE_SWARM = "leave_swarm"
    NO_ACTION = "no_action"


@dataclass(frozen=True)
class ResponseResult:
    """Result of a response action."""
    action: ResponseAction
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None


class ResponseHandlerError(Exception):
    """Error handling response."""


class ResponseHandler:
    """Handles Claude subagent responses by sending via SwarmClient."""

    def __init__(self, db_manager: DatabaseManager, client: SwarmClient) -> None:
        if not db_manager.is_initialized:
            raise ResponseHandlerError("Database not initialized")
        self._db = db_manager
        self._client = client

    async def send_reply(
        self,
        original_message_id: str,
        swarm_id: UUID,
        content: str,
        recipient: str = "broadcast",
        priority: Priority = Priority.NORMAL,
        thread_id: Optional[UUID] = None,
    ) -> ResponseResult:
        """Send a reply to a swarm message."""
        action = ResponseAction.REPLY_DIRECT if recipient != "broadcast" else ResponseAction.REPLY
        try:
            msg = await self._client.send_message(
                swarm_id=swarm_id,
                content=content,
                recipient=recipient,
                message_type=MessageType.MESSAGE,
                priority=priority,
                in_reply_to=UUID(original_message_id),
                thread_id=thread_id,
            )
            await self._mark_processed(original_message_id)
            return ResponseResult(action=action, success=True, message_id=str(msg.message_id))
        except Exception as e:
            await self._mark_failed(original_message_id, str(e))
            return ResponseResult(action=action, success=False, error=str(e))

    async def acknowledge(self, message_id: str) -> ResponseResult:
        """Acknowledge message without sending a reply."""
        try:
            await self._mark_processed(message_id)
            return ResponseResult(action=ResponseAction.NO_ACTION, success=True)
        except Exception as e:
            return ResponseResult(action=ResponseAction.NO_ACTION, success=False, error=str(e))

    async def leave_swarm(self, message_id: str, swarm_id: UUID) -> ResponseResult:
        """Leave a swarm in response to a message."""
        try:
            await self._client.leave_swarm(swarm_id)
            await self._mark_processed(message_id)
            return ResponseResult(action=ResponseAction.LEAVE_SWARM, success=True)
        except Exception as e:
            await self._mark_failed(message_id, str(e))
            return ResponseResult(action=ResponseAction.LEAVE_SWARM, success=False, error=str(e))

    async def _mark_processed(self, message_id: str) -> None:
        """Mark message as completed in queue."""
        async with self._db.connection() as conn:
            repo = MessageRepository(conn)
            await repo.complete(message_id)

    async def _mark_failed(self, message_id: str, error: str) -> None:
        """Mark message as failed in queue."""
        async with self._db.connection() as conn:
            repo = MessageRepository(conn)
            await repo.fail(message_id, error)
