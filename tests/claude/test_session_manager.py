"""Tests for session manager."""
import json
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from src.claude.session_manager import (
    SessionManager,
    SessionState,
    SessionData,
    SessionManagerError,
)


class TestSessionManager:
    """Test session management functionality."""

    @pytest.fixture
    def session_file(self, tmp_path: Path) -> Path:
        """Create temporary session file path."""
        return tmp_path / "session.json"

    def test_no_session_returns_none(self, session_file: Path) -> None:
        """No session file should return None."""
        manager = SessionManager(session_file)
        assert manager.get_current_session() is None

    def test_should_resume_false_no_session(self, session_file: Path) -> None:
        """should_resume should return False with no session."""
        manager = SessionManager(session_file)
        assert manager.should_resume() is False

    def test_start_session_creates_active(self, session_file: Path) -> None:
        """Starting session should create ACTIVE state."""
        manager = SessionManager(session_file)
        manager.start_session("session-123", swarm_id="swarm-1")

        session = manager.get_current_session()
        assert session is not None
        assert session.session_id == "session-123"
        assert session.state == SessionState.ACTIVE
        assert session.current_swarm == "swarm-1"

    def test_session_persisted_to_file(self, session_file: Path) -> None:
        """Session should be written to file."""
        manager = SessionManager(session_file)
        manager.start_session("session-123")

        assert session_file.exists()
        data = json.loads(session_file.read_text())
        assert data["session_id"] == "session-123"
        assert data["state"] == "active"

    def test_session_loads_from_file(self, session_file: Path) -> None:
        """Session should load from existing file."""
        # Create session with first manager
        manager1 = SessionManager(session_file)
        manager1.start_session("session-123")

        # Load with new manager
        manager2 = SessionManager(session_file)
        session = manager2.get_current_session()
        assert session is not None
        assert session.session_id == "session-123"

    def test_should_resume_true_for_active(self, session_file: Path) -> None:
        """should_resume should return True for active session."""
        manager = SessionManager(session_file)
        manager.start_session("session-123")

        assert manager.should_resume() is True

    def test_should_resume_false_for_timeout(self, session_file: Path) -> None:
        """should_resume should return False for timed out session."""
        manager = SessionManager(session_file, session_timeout_minutes=30)
        manager.start_session("session-123")

        # Manually backdate the session
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(minutes=60)
        data = json.loads(session_file.read_text())
        data["last_active"] = old_time.isoformat()
        session_file.write_text(json.dumps(data))

        # Create new manager to load old session
        manager2 = SessionManager(session_file, session_timeout_minutes=30)
        assert manager2.should_resume() is False

    def test_update_activity(self, session_file: Path) -> None:
        """Update activity should update last_active and counts."""
        manager = SessionManager(session_file)
        manager.start_session("session-123")
        manager.update_activity(messages_processed=5, context_summary="Test context")

        session = manager.get_current_session()
        assert session is not None
        assert session.messages_processed == 5
        assert session.context_summary == "Test context"

    def test_update_activity_accumulates(self, session_file: Path) -> None:
        """Multiple updates should accumulate message count."""
        manager = SessionManager(session_file)
        manager.start_session("session-123")
        manager.update_activity(messages_processed=5)
        manager.update_activity(messages_processed=3)

        session = manager.get_current_session()
        assert session is not None
        assert session.messages_processed == 8

    def test_update_activity_no_session_raises(self, session_file: Path) -> None:
        """Update with no session should raise error."""
        manager = SessionManager(session_file)
        with pytest.raises(SessionManagerError, match="No active session"):
            manager.update_activity(messages_processed=1)

    def test_suspend_session(self, session_file: Path) -> None:
        """Suspend should change state to SUSPENDED."""
        manager = SessionManager(session_file)
        manager.start_session("session-123")
        manager.suspend_session("Context for resume")

        session = manager.get_current_session()
        assert session is not None
        assert session.state == SessionState.SUSPENDED
        assert session.context_summary == "Context for resume"

    def test_should_resume_true_for_suspended(self, session_file: Path) -> None:
        """should_resume should return True for suspended session."""
        manager = SessionManager(session_file)
        manager.start_session("session-123")
        manager.suspend_session("Context")

        assert manager.should_resume() is True

    def test_end_session_clears(self, session_file: Path) -> None:
        """End session should clear state and delete file."""
        manager = SessionManager(session_file)
        manager.start_session("session-123")
        manager.end_session()

        assert manager.get_current_session() is None
        assert not session_file.exists()

    def test_corrupted_file_raises_and_clears(self, session_file: Path) -> None:
        """Corrupted session file should raise and be cleared."""
        session_file.write_text("not valid json")

        manager = SessionManager(session_file)
        with pytest.raises(SessionManagerError, match="Corrupted session file"):
            manager.get_current_session()

        assert not session_file.exists()

    def test_should_resume_false_for_idle(self, session_file: Path) -> None:
        """should_resume should return False for IDLE state."""
        # Create a session file with IDLE state
        data = {
            "session_id": "session-123",
            "state": "idle",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "last_active": datetime.now(timezone.utc).isoformat(),
        }
        session_file.write_text(json.dumps(data))

        manager = SessionManager(session_file)
        assert manager.should_resume() is False
