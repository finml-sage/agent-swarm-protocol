"""Notification preferences for wake triggers vs silent queuing."""
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Optional


class NotificationLevel(IntEnum):
    """Notification urgency levels, ordered by priority."""

    SILENT = 0  # Queue without waking
    NORMAL = 1  # Wake on next poll cycle
    URGENT = 2  # Immediate wake


class WakeCondition(Enum):
    """Conditions that can trigger a wake."""

    ANY_MESSAGE = "any_message"
    DIRECT_MENTION = "direct_mention"
    HIGH_PRIORITY = "high_priority"
    FROM_SPECIFIC_AGENT = "from_specific_agent"
    KEYWORD_MATCH = "keyword_match"
    SWARM_SYSTEM_MESSAGE = "swarm_system_message"


@dataclass(frozen=True)
class NotificationPreferences:
    """User preferences for when to wake vs queue silently."""

    enabled: bool = True
    default_level: NotificationLevel = NotificationLevel.NORMAL
    wake_conditions: tuple[WakeCondition, ...] = (WakeCondition.ANY_MESSAGE,)
    watched_agents: tuple[str, ...] = ()
    watched_keywords: tuple[str, ...] = ()
    muted_swarms: tuple[str, ...] = ()
    quiet_hours: Optional[tuple[int, int]] = None  # (start_hour, end_hour) UTC

    def __post_init__(self) -> None:
        if self.quiet_hours is not None:
            start, end = self.quiet_hours
            if not (0 <= start <= 23) or not (0 <= end <= 23):
                raise ValueError("Quiet hours must be 0-23")

    def should_wake(
        self,
        sender_id: str,
        swarm_id: str,
        content: str,
        is_direct_mention: bool,
        is_high_priority: bool,
        is_system_message: bool,
        current_hour: int,
    ) -> NotificationLevel:
        """
        Determine notification level for a message.

        Returns SILENT if message should be queued without waking,
        NORMAL for standard wake, URGENT for immediate wake.
        """
        if not self.enabled:
            return NotificationLevel.SILENT

        if swarm_id in self.muted_swarms:
            return NotificationLevel.SILENT

        if self._is_quiet_hours(current_hour):
            # During quiet hours, only wake for urgent conditions
            if is_high_priority or is_system_message:
                return NotificationLevel.URGENT
            return NotificationLevel.SILENT

        # Check wake conditions
        level = NotificationLevel.SILENT

        for condition in self.wake_conditions:
            match condition:
                case WakeCondition.ANY_MESSAGE:
                    level = max(level, self.default_level)
                case WakeCondition.DIRECT_MENTION:
                    if is_direct_mention:
                        level = NotificationLevel.URGENT
                case WakeCondition.HIGH_PRIORITY:
                    if is_high_priority:
                        level = NotificationLevel.URGENT
                case WakeCondition.FROM_SPECIFIC_AGENT:
                    if sender_id in self.watched_agents:
                        level = NotificationLevel.URGENT
                case WakeCondition.KEYWORD_MATCH:
                    if self._matches_keywords(content):
                        level = NotificationLevel.URGENT
                case WakeCondition.SWARM_SYSTEM_MESSAGE:
                    if is_system_message:
                        level = NotificationLevel.URGENT

        return level

    def _is_quiet_hours(self, current_hour: int) -> bool:
        """Check if current hour is within quiet hours."""
        if self.quiet_hours is None:
            return False
        start, end = self.quiet_hours
        if start <= end:
            return start <= current_hour < end
        # Handle wrap-around (e.g., 22:00 to 06:00)
        return current_hour >= start or current_hour < end

    def _matches_keywords(self, content: str) -> bool:
        """Check if content contains any watched keywords."""
        content_lower = content.lower()
        return any(kw.lower() in content_lower for kw in self.watched_keywords)
