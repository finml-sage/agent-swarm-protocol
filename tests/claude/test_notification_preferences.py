"""Tests for notification preferences."""
import pytest
from src.claude.notification_preferences import (
    NotificationPreferences,
    NotificationLevel,
    WakeCondition,
)


class TestNotificationPreferences:
    """Test notification preference evaluation."""

    def test_disabled_returns_silent(self) -> None:
        """Disabled preferences should always return SILENT."""
        prefs = NotificationPreferences(enabled=False)
        level = prefs.should_wake(
            sender_id="agent-1",
            swarm_id="swarm-1",
            content="hello",
            is_direct_mention=True,
            is_high_priority=True,
            is_system_message=False,
            current_hour=12,
        )
        assert level == NotificationLevel.SILENT

    def test_muted_swarm_returns_silent(self) -> None:
        """Messages from muted swarms should be silent."""
        prefs = NotificationPreferences(
            muted_swarms=("swarm-1",),
        )
        level = prefs.should_wake(
            sender_id="agent-1",
            swarm_id="swarm-1",
            content="hello",
            is_direct_mention=False,
            is_high_priority=False,
            is_system_message=False,
            current_hour=12,
        )
        assert level == NotificationLevel.SILENT

    def test_any_message_wakes(self) -> None:
        """ANY_MESSAGE condition should wake on all messages."""
        prefs = NotificationPreferences(
            wake_conditions=(WakeCondition.ANY_MESSAGE,),
            default_level=NotificationLevel.NORMAL,
        )
        level = prefs.should_wake(
            sender_id="agent-1",
            swarm_id="swarm-1",
            content="hello",
            is_direct_mention=False,
            is_high_priority=False,
            is_system_message=False,
            current_hour=12,
        )
        assert level == NotificationLevel.NORMAL

    def test_direct_mention_urgent(self) -> None:
        """Direct mentions should be URGENT."""
        prefs = NotificationPreferences(
            wake_conditions=(WakeCondition.DIRECT_MENTION,),
        )
        level = prefs.should_wake(
            sender_id="agent-1",
            swarm_id="swarm-1",
            content="@agent hello",
            is_direct_mention=True,
            is_high_priority=False,
            is_system_message=False,
            current_hour=12,
        )
        assert level == NotificationLevel.URGENT

    def test_high_priority_urgent(self) -> None:
        """High priority messages should be URGENT."""
        prefs = NotificationPreferences(
            wake_conditions=(WakeCondition.HIGH_PRIORITY,),
        )
        level = prefs.should_wake(
            sender_id="agent-1",
            swarm_id="swarm-1",
            content="important",
            is_direct_mention=False,
            is_high_priority=True,
            is_system_message=False,
            current_hour=12,
        )
        assert level == NotificationLevel.URGENT

    def test_watched_agent_urgent(self) -> None:
        """Messages from watched agents should be URGENT."""
        prefs = NotificationPreferences(
            wake_conditions=(WakeCondition.FROM_SPECIFIC_AGENT,),
            watched_agents=("important-agent",),
        )
        level = prefs.should_wake(
            sender_id="important-agent",
            swarm_id="swarm-1",
            content="hello",
            is_direct_mention=False,
            is_high_priority=False,
            is_system_message=False,
            current_hour=12,
        )
        assert level == NotificationLevel.URGENT

    def test_keyword_match_urgent(self) -> None:
        """Messages with keywords should be URGENT."""
        prefs = NotificationPreferences(
            wake_conditions=(WakeCondition.KEYWORD_MATCH,),
            watched_keywords=("urgent", "help"),
        )
        level = prefs.should_wake(
            sender_id="agent-1",
            swarm_id="swarm-1",
            content="I need URGENT help!",
            is_direct_mention=False,
            is_high_priority=False,
            is_system_message=False,
            current_hour=12,
        )
        assert level == NotificationLevel.URGENT

    def test_system_message_urgent(self) -> None:
        """System messages should be URGENT when configured."""
        prefs = NotificationPreferences(
            wake_conditions=(WakeCondition.SWARM_SYSTEM_MESSAGE,),
        )
        level = prefs.should_wake(
            sender_id="system",
            swarm_id="swarm-1",
            content="agent-x joined",
            is_direct_mention=False,
            is_high_priority=False,
            is_system_message=True,
            current_hour=12,
        )
        assert level == NotificationLevel.URGENT

    def test_quiet_hours_silent(self) -> None:
        """Normal messages during quiet hours should be SILENT."""
        prefs = NotificationPreferences(
            wake_conditions=(WakeCondition.ANY_MESSAGE,),
            quiet_hours=(22, 6),
        )
        # At 23:00, should be silent
        level = prefs.should_wake(
            sender_id="agent-1",
            swarm_id="swarm-1",
            content="hello",
            is_direct_mention=False,
            is_high_priority=False,
            is_system_message=False,
            current_hour=23,
        )
        assert level == NotificationLevel.SILENT

    def test_quiet_hours_urgent_wakes(self) -> None:
        """Urgent messages during quiet hours should still wake."""
        prefs = NotificationPreferences(
            wake_conditions=(WakeCondition.ANY_MESSAGE,),
            quiet_hours=(22, 6),
        )
        # High priority during quiet hours
        level = prefs.should_wake(
            sender_id="agent-1",
            swarm_id="swarm-1",
            content="emergency",
            is_direct_mention=False,
            is_high_priority=True,
            is_system_message=False,
            current_hour=23,
        )
        assert level == NotificationLevel.URGENT

    def test_quiet_hours_wraparound(self) -> None:
        """Quiet hours that wrap midnight should work correctly."""
        prefs = NotificationPreferences(
            wake_conditions=(WakeCondition.ANY_MESSAGE,),
            quiet_hours=(22, 6),
        )
        # At 3am, should be quiet
        level = prefs.should_wake(
            sender_id="agent-1",
            swarm_id="swarm-1",
            content="hello",
            is_direct_mention=False,
            is_high_priority=False,
            is_system_message=False,
            current_hour=3,
        )
        assert level == NotificationLevel.SILENT

        # At 12pm, should not be quiet
        level = prefs.should_wake(
            sender_id="agent-1",
            swarm_id="swarm-1",
            content="hello",
            is_direct_mention=False,
            is_high_priority=False,
            is_system_message=False,
            current_hour=12,
        )
        assert level == NotificationLevel.NORMAL

    def test_invalid_quiet_hours_raises(self) -> None:
        """Invalid quiet hours should raise ValueError."""
        with pytest.raises(ValueError, match="Quiet hours must be 0-23"):
            NotificationPreferences(quiet_hours=(25, 6))

    def test_multiple_conditions_highest_wins(self) -> None:
        """When multiple conditions match, highest level wins."""
        prefs = NotificationPreferences(
            wake_conditions=(
                WakeCondition.ANY_MESSAGE,
                WakeCondition.DIRECT_MENTION,
            ),
            default_level=NotificationLevel.NORMAL,
        )
        # Direct mention should result in URGENT even with ANY_MESSAGE
        level = prefs.should_wake(
            sender_id="agent-1",
            swarm_id="swarm-1",
            content="hello",
            is_direct_mention=True,
            is_high_priority=False,
            is_system_message=False,
            current_hour=12,
        )
        assert level == NotificationLevel.URGENT
