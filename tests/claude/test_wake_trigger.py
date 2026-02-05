"""Tests for wake trigger."""
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from src.state import DatabaseManager
from src.state.models import QueuedMessage, MessageStatus
from src.claude.wake_trigger import (
    WakeTrigger,
    WakeDecision,
    WakeEvent,
    WakeTriggerError,
)
from src.claude.notification_preferences import (
    NotificationPreferences,
    NotificationLevel,
    WakeCondition,
)


class TestWakeTrigger:
    """Test wake trigger functionality."""

    @pytest.fixture
    async def db_manager(self, tmp_path: Path) -> DatabaseManager:
        """Create initialized database manager."""
        db_path = tmp_path / "test.db"
        manager = DatabaseManager(db_path)
        await manager.initialize()
        return manager

    @pytest.fixture
    def sample_message(self) -> QueuedMessage:
        """Create sample queued message."""
        return QueuedMessage(
            message_id="msg-123",
            swarm_id="swarm-456",
            sender_id="agent-sender",
            message_type="message",
            content="Hello swarm!",
            received_at=datetime.now(timezone.utc),
            status=MessageStatus.PENDING,
        )

    @pytest.fixture
    def default_prefs(self) -> NotificationPreferences:
        """Create default notification preferences."""
        return NotificationPreferences(
            wake_conditions=(WakeCondition.ANY_MESSAGE,),
        )

    def test_uninitialized_db_raises(self, tmp_path: Path) -> None:
        """Uninitialized database should raise error."""
        db = DatabaseManager(tmp_path / "test.db")
        with pytest.raises(WakeTriggerError, match="Database not initialized"):
            WakeTrigger(
                db, "http://localhost:8080/api/wake", NotificationPreferences()
            )

    def test_empty_endpoint_raises(self, db_manager: DatabaseManager) -> None:
        """Empty wake endpoint should raise error."""
        with pytest.raises(WakeTriggerError, match="Wake endpoint required"):
            WakeTrigger(db_manager, "", NotificationPreferences())

    @pytest.mark.asyncio
    async def test_process_message_wake_decision(
        self,
        db_manager: DatabaseManager,
        sample_message: QueuedMessage,
        default_prefs: NotificationPreferences,
    ) -> None:
        """Process message should return WAKE for normal message."""
        with patch("src.claude.wake_trigger.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_instance.post.return_value = AsyncMock(
                status_code=200, text=""
            )
            mock_client.return_value = mock_instance

            trigger = WakeTrigger(
                db_manager,
                "http://localhost:8080/api/wake",
                default_prefs,
            )
            event = await trigger.process_message(sample_message)

            assert event.decision == WakeDecision.WAKE

    @pytest.mark.asyncio
    async def test_process_muted_sender_skips(
        self,
        db_manager: DatabaseManager,
        sample_message: QueuedMessage,
        default_prefs: NotificationPreferences,
    ) -> None:
        """Muted sender should result in SKIP decision."""
        from src.state import MuteRepository

        async with db_manager.connection() as conn:
            repo = MuteRepository(conn)
            await repo.mute_agent(sample_message.sender_id)

        trigger = WakeTrigger(
            db_manager, "http://localhost:8080/api/wake", default_prefs
        )
        event = await trigger.process_message(sample_message)

        assert event.decision == WakeDecision.SKIP

    @pytest.mark.asyncio
    async def test_process_muted_swarm_skips(
        self,
        db_manager: DatabaseManager,
        sample_message: QueuedMessage,
        default_prefs: NotificationPreferences,
    ) -> None:
        """Muted swarm should result in SKIP decision."""
        from src.state import MuteRepository

        async with db_manager.connection() as conn:
            repo = MuteRepository(conn)
            await repo.mute_swarm(sample_message.swarm_id)

        trigger = WakeTrigger(
            db_manager, "http://localhost:8080/api/wake", default_prefs
        )
        event = await trigger.process_message(sample_message)

        assert event.decision == WakeDecision.SKIP

    @pytest.mark.asyncio
    async def test_process_silent_queues(
        self,
        db_manager: DatabaseManager,
        sample_message: QueuedMessage,
    ) -> None:
        """SILENT notification level should result in QUEUE."""
        prefs = NotificationPreferences(
            enabled=False,  # Disabled returns SILENT
        )
        trigger = WakeTrigger(
            db_manager, "http://localhost:8080/api/wake", prefs
        )
        event = await trigger.process_message(sample_message)

        assert event.decision == WakeDecision.QUEUE
        assert event.notification_level == NotificationLevel.SILENT

    @pytest.mark.asyncio
    async def test_callback_notified(
        self,
        db_manager: DatabaseManager,
        sample_message: QueuedMessage,
        default_prefs: NotificationPreferences,
    ) -> None:
        """Registered callbacks should be called with event."""
        with patch("src.claude.wake_trigger.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_instance.post.return_value = AsyncMock(status_code=200)
            mock_client.return_value = mock_instance

            trigger = WakeTrigger(
                db_manager, "http://localhost:8080/api/wake", default_prefs
            )

            callback = AsyncMock()
            trigger.add_callback(callback)

            await trigger.process_message(sample_message)

            callback.assert_called_once()
            event = callback.call_args[0][0]
            assert isinstance(event, WakeEvent)
            assert event.message == sample_message

    @pytest.mark.asyncio
    async def test_wake_posts_to_endpoint(
        self,
        db_manager: DatabaseManager,
        sample_message: QueuedMessage,
        default_prefs: NotificationPreferences,
    ) -> None:
        """WAKE decision should POST to wake endpoint."""
        with patch("src.claude.wake_trigger.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_instance.post.return_value = mock_response
            mock_client.return_value = mock_instance

            trigger = WakeTrigger(
                db_manager, "http://localhost:8080/api/wake", default_prefs
            )
            await trigger.process_message(sample_message)

            mock_instance.post.assert_called_once()
            call_args = mock_instance.post.call_args
            assert call_args[0][0] == "http://localhost:8080/api/wake"
            assert "message_id" in call_args[1]["json"]

    @pytest.mark.asyncio
    async def test_wake_endpoint_error_raises(
        self,
        db_manager: DatabaseManager,
        sample_message: QueuedMessage,
        default_prefs: NotificationPreferences,
    ) -> None:
        """Failed POST should raise WakeTriggerError."""
        with patch("src.claude.wake_trigger.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_response = AsyncMock()
            mock_response.status_code = 500
            mock_response.text = "Internal error"
            mock_instance.post.return_value = mock_response
            mock_client.return_value = mock_instance

            trigger = WakeTrigger(
                db_manager, "http://localhost:8080/api/wake", default_prefs
            )

            with pytest.raises(WakeTriggerError, match="Wake endpoint returned 500"):
                await trigger.process_message(sample_message)
