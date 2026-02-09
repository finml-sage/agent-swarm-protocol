"""Tests for response handler."""
import pytest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4, UUID
from unittest.mock import AsyncMock, MagicMock, patch
from src.state import DatabaseManager, InboxRepository
from src.state.models.inbox import InboxMessage, InboxStatus
from src.client import SwarmClient
from src.client.types import MessageType, Priority
from src.claude.response_handler import (
    ResponseHandler,
    ResponseAction,
    ResponseResult,
    ResponseHandlerError,
)


class TestResponseHandler:
    """Test response handler functionality."""

    @pytest.fixture
    async def db_manager(self, tmp_path: Path) -> DatabaseManager:
        """Create initialized database manager."""
        db_path = tmp_path / "test.db"
        manager = DatabaseManager(db_path)
        await manager.initialize()
        return manager

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create mock SwarmClient."""
        client = MagicMock()
        mock_message = MagicMock()
        mock_message.message_id = uuid4()
        client.send_message = AsyncMock(return_value=mock_message)
        client.leave_swarm = AsyncMock()
        return client

    @pytest.fixture
    async def sample_message(self, db_manager: DatabaseManager) -> InboxMessage:
        """Create sample inbox message in database."""
        msg = InboxMessage(
            message_id=str(uuid4()),
            swarm_id=str(uuid4()),
            sender_id="agent-sender",
            message_type="message",
            content="Hello swarm!",
            received_at=datetime.now(timezone.utc),
            status=InboxStatus.UNREAD,
        )
        async with db_manager.connection() as conn:
            repo = InboxRepository(conn)
            await repo.insert(msg)
        return msg

    def test_uninitialized_db_raises(
        self, tmp_path: Path, mock_client: AsyncMock
    ) -> None:
        """Uninitialized database should raise error."""
        db = DatabaseManager(tmp_path / "test.db")
        with pytest.raises(ResponseHandlerError, match="Database not initialized"):
            ResponseHandler(db, mock_client)

    @pytest.mark.asyncio
    async def test_send_reply_broadcast(
        self,
        db_manager: DatabaseManager,
        mock_client: AsyncMock,
        sample_message: InboxMessage,
    ) -> None:
        """Broadcast reply should use SwarmClient."""
        handler = ResponseHandler(db_manager, mock_client)
        result = await handler.send_reply(
            original_message_id=sample_message.message_id,
            swarm_id=UUID(sample_message.swarm_id),
            content="Response content",
        )

        assert result.success is True
        assert result.action == ResponseAction.REPLY
        assert result.message_id is not None

        mock_client.send_message.assert_called_once()
        call_kwargs = mock_client.send_message.call_args.kwargs
        assert call_kwargs["content"] == "Response content"
        assert call_kwargs["recipient"] == "broadcast"

    @pytest.mark.asyncio
    async def test_send_reply_direct(
        self,
        db_manager: DatabaseManager,
        mock_client: AsyncMock,
        sample_message: InboxMessage,
    ) -> None:
        """Direct reply should set specific recipient."""
        handler = ResponseHandler(db_manager, mock_client)
        result = await handler.send_reply(
            original_message_id=sample_message.message_id,
            swarm_id=UUID(sample_message.swarm_id),
            content="Private message",
            recipient="specific-agent",
        )

        assert result.success is True
        assert result.action == ResponseAction.REPLY_DIRECT

        call_kwargs = mock_client.send_message.call_args.kwargs
        assert call_kwargs["recipient"] == "specific-agent"

    @pytest.mark.asyncio
    async def test_send_reply_marks_read(
        self,
        db_manager: DatabaseManager,
        mock_client: AsyncMock,
        sample_message: InboxMessage,
    ) -> None:
        """Successful reply should mark message as read."""
        handler = ResponseHandler(db_manager, mock_client)
        await handler.send_reply(
            original_message_id=sample_message.message_id,
            swarm_id=UUID(sample_message.swarm_id),
            content="Response",
        )

        async with db_manager.connection() as conn:
            repo = InboxRepository(conn)
            msg = await repo.get_by_id(sample_message.message_id)
            assert msg is not None
            assert msg.status == InboxStatus.READ

    @pytest.mark.asyncio
    async def test_send_reply_failure_marks_read(
        self,
        db_manager: DatabaseManager,
        mock_client: AsyncMock,
        sample_message: InboxMessage,
    ) -> None:
        """Failed reply should still mark message as read (it was processed)."""
        mock_client.send_message.side_effect = Exception("Network error")

        handler = ResponseHandler(db_manager, mock_client)
        result = await handler.send_reply(
            original_message_id=sample_message.message_id,
            swarm_id=UUID(sample_message.swarm_id),
            content="Response",
        )

        assert result.success is False
        assert result.error == "Network error"

        async with db_manager.connection() as conn:
            repo = InboxRepository(conn)
            msg = await repo.get_by_id(sample_message.message_id)
            assert msg is not None
            assert msg.status == InboxStatus.READ

    @pytest.mark.asyncio
    async def test_acknowledge(
        self,
        db_manager: DatabaseManager,
        mock_client: AsyncMock,
        sample_message: InboxMessage,
    ) -> None:
        """Acknowledge should mark read without sending."""
        handler = ResponseHandler(db_manager, mock_client)
        result = await handler.acknowledge(sample_message.message_id)

        assert result.success is True
        assert result.action == ResponseAction.NO_ACTION
        mock_client.send_message.assert_not_called()

        async with db_manager.connection() as conn:
            repo = InboxRepository(conn)
            msg = await repo.get_by_id(sample_message.message_id)
            assert msg is not None
            assert msg.status == InboxStatus.READ

    @pytest.mark.asyncio
    async def test_leave_swarm(
        self,
        db_manager: DatabaseManager,
        mock_client: AsyncMock,
        sample_message: InboxMessage,
    ) -> None:
        """Leave swarm should call client leave."""
        handler = ResponseHandler(db_manager, mock_client)
        result = await handler.leave_swarm(
            message_id=sample_message.message_id,
            swarm_id=UUID(sample_message.swarm_id),
        )

        assert result.success is True
        assert result.action == ResponseAction.LEAVE_SWARM
        mock_client.leave_swarm.assert_called_once()

    @pytest.mark.asyncio
    async def test_leave_swarm_failure(
        self,
        db_manager: DatabaseManager,
        mock_client: AsyncMock,
        sample_message: InboxMessage,
    ) -> None:
        """Failed leave should return error result."""
        mock_client.leave_swarm.side_effect = Exception("Not a member")

        handler = ResponseHandler(db_manager, mock_client)
        result = await handler.leave_swarm(
            message_id=sample_message.message_id,
            swarm_id=UUID(sample_message.swarm_id),
        )

        assert result.success is False
        assert result.error == "Not a member"

    @pytest.mark.asyncio
    async def test_send_reply_with_priority(
        self,
        db_manager: DatabaseManager,
        mock_client: AsyncMock,
        sample_message: InboxMessage,
    ) -> None:
        """Reply should pass priority to client."""
        handler = ResponseHandler(db_manager, mock_client)
        await handler.send_reply(
            original_message_id=sample_message.message_id,
            swarm_id=UUID(sample_message.swarm_id),
            content="Urgent message",
            priority=Priority.HIGH,
        )

        call_kwargs = mock_client.send_message.call_args.kwargs
        assert call_kwargs["priority"] == Priority.HIGH

    @pytest.mark.asyncio
    async def test_send_reply_with_thread(
        self,
        db_manager: DatabaseManager,
        mock_client: AsyncMock,
        sample_message: InboxMessage,
    ) -> None:
        """Reply should pass thread_id to client."""
        thread_id = uuid4()
        handler = ResponseHandler(db_manager, mock_client)
        await handler.send_reply(
            original_message_id=sample_message.message_id,
            swarm_id=UUID(sample_message.swarm_id),
            content="Thread reply",
            thread_id=thread_id,
        )

        call_kwargs = mock_client.send_message.call_args.kwargs
        assert call_kwargs["thread_id"] == thread_id
