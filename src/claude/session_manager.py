"""Session management for Claude subagent continuity."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Optional
import json


class SessionState(Enum):
    """Claude subagent session states."""
    IDLE = "idle"
    ACTIVE = "active"
    SUSPENDED = "suspended"


@dataclass
class SessionData:
    """Data about a Claude session."""
    session_id: str
    state: SessionState
    started_at: datetime
    last_active: datetime
    messages_processed: int = 0
    current_swarm: Optional[str] = None
    context_summary: Optional[str] = None


class SessionManagerError(Exception):
    """Error in session management."""


class SessionManager:
    """Manages Claude subagent session state for resume vs new session decisions."""

    def __init__(self, session_file: Path, session_timeout_minutes: int = 30) -> None:
        self._session_file = session_file
        self._session_timeout = session_timeout_minutes
        self._current_session: Optional[SessionData] = None

    def get_current_session(self) -> Optional[SessionData]:
        """Get current session if active or suspended."""
        if self._current_session is None:
            self._load_session()
        return self._current_session

    def should_resume(self) -> bool:
        """Return True if existing session should be resumed (within timeout)."""
        session = self.get_current_session()
        if session is None or session.state == SessionState.IDLE:
            return False
        elapsed = datetime.now(timezone.utc) - session.last_active
        return elapsed.total_seconds() <= self._session_timeout * 60

    def start_session(self, session_id: str, swarm_id: Optional[str] = None) -> None:
        """Start a new session."""
        now = datetime.now(timezone.utc)
        self._current_session = SessionData(
            session_id=session_id, state=SessionState.ACTIVE, started_at=now,
            last_active=now, current_swarm=swarm_id,
        )
        self._save_session()

    def update_activity(self, messages_processed: int = 0, context_summary: Optional[str] = None) -> None:
        """Update session with recent activity."""
        if self._current_session is None:
            raise SessionManagerError("No active session to update")
        self._current_session = SessionData(
            session_id=self._current_session.session_id, state=SessionState.ACTIVE,
            started_at=self._current_session.started_at, last_active=datetime.now(timezone.utc),
            messages_processed=self._current_session.messages_processed + messages_processed,
            current_swarm=self._current_session.current_swarm,
            context_summary=context_summary or self._current_session.context_summary,
        )
        self._save_session()

    def suspend_session(self, context_summary: str) -> None:
        """Suspend session for later resume."""
        if self._current_session is None:
            raise SessionManagerError("No active session to suspend")
        self._current_session = SessionData(
            session_id=self._current_session.session_id, state=SessionState.SUSPENDED,
            started_at=self._current_session.started_at, last_active=datetime.now(timezone.utc),
            messages_processed=self._current_session.messages_processed,
            current_swarm=self._current_session.current_swarm, context_summary=context_summary,
        )
        self._save_session()

    def end_session(self) -> None:
        """End the current session."""
        self._current_session = None
        if self._session_file.exists():
            self._session_file.unlink()

    def _load_session(self) -> None:
        """Load session from file if exists."""
        if not self._session_file.exists():
            return
        try:
            data = json.loads(self._session_file.read_text())
            self._current_session = SessionData(
                session_id=data["session_id"], state=SessionState(data["state"]),
                started_at=datetime.fromisoformat(data["started_at"]),
                last_active=datetime.fromisoformat(data["last_active"]),
                messages_processed=data.get("messages_processed", 0),
                current_swarm=data.get("current_swarm"),
                context_summary=data.get("context_summary"),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self._session_file.unlink()
            raise SessionManagerError(f"Corrupted session file: {e}") from e

    def _save_session(self) -> None:
        """Persist session to file."""
        if self._current_session is None:
            return
        self._session_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "session_id": self._current_session.session_id,
            "state": self._current_session.state.value,
            "started_at": self._current_session.started_at.isoformat(),
            "last_active": self._current_session.last_active.isoformat(),
            "messages_processed": self._current_session.messages_processed,
            "current_swarm": self._current_session.current_swarm,
            "context_summary": self._current_session.context_summary,
        }
        self._session_file.write_text(json.dumps(data, indent=2))
