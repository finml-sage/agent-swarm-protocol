"""Wake trigger for Claude subagent activation."""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Awaitable

import httpx

from src.state import DatabaseManager, QueuedMessage
from src.claude.notification_preferences import NotificationPreferences, NotificationLevel
from src.claude.context_loader import ContextLoader, SwarmContext


class WakeDecision(Enum):
    """Decision on how to handle a message."""
    WAKE = "wake"
    QUEUE = "queue"
    SKIP = "skip"


@dataclass(frozen=True)
class WakeEvent:
    """Event that may trigger a wake."""
    message: QueuedMessage
    context: SwarmContext
    decision: WakeDecision
    notification_level: NotificationLevel


WakeCallback = Callable[[WakeEvent], Awaitable[None]]


class WakeTriggerError(Exception):
    """Error in wake trigger processing."""


class WakeTrigger:
    """Triggers Claude subagent wake when messages arrive via POST to /api/wake."""

    def __init__(
        self, db_manager: DatabaseManager, wake_endpoint: str,
        preferences: NotificationPreferences, wake_timeout: float = 5.0,
    ) -> None:
        if not db_manager.is_initialized:
            raise WakeTriggerError("Database not initialized")
        if not wake_endpoint:
            raise WakeTriggerError("Wake endpoint required")
        self._db = db_manager
        self._wake_endpoint = wake_endpoint
        self._preferences = preferences
        self._wake_timeout = wake_timeout
        self._context_loader = ContextLoader(db_manager)
        self._callbacks: list[WakeCallback] = []

    def add_callback(self, callback: WakeCallback) -> None:
        """Register callback for wake events."""
        self._callbacks.append(callback)

    async def process_message(self, message: QueuedMessage) -> WakeEvent:
        """Process incoming message and determine wake action."""
        context = await self._context_loader.load_context(message)
        decision = self._make_decision(context)
        level = self._get_notification_level(context)
        event = WakeEvent(message=message, context=context, decision=decision, notification_level=level)
        if decision == WakeDecision.WAKE:
            await self._trigger_wake(event)
        await self._notify_callbacks(event)
        return event

    def _make_decision(self, context: SwarmContext) -> WakeDecision:
        """Decide how to handle the message based on context."""
        if context.is_sender_muted or context.is_swarm_muted:
            return WakeDecision.SKIP
        level = self._get_notification_level(context)
        return WakeDecision.QUEUE if level == NotificationLevel.SILENT else WakeDecision.WAKE

    def _get_notification_level(self, context: SwarmContext) -> NotificationLevel:
        """Determine notification level from preferences and context."""
        current_hour = datetime.now(timezone.utc).hour
        is_direct = context.message.message_type == "notification"
        is_high_priority = context.message.message_type == "high_priority"
        is_system = context.message.message_type == "system"
        return self._preferences.should_wake(
            sender_id=context.message.sender_id, swarm_id=context.message.swarm_id,
            content=context.message.content, is_direct_mention=is_direct,
            is_high_priority=is_high_priority, is_system_message=is_system,
            current_hour=current_hour,
        )

    async def _trigger_wake(self, event: WakeEvent) -> None:
        """POST to wake endpoint to trigger Claude activation."""
        payload = {
            "message_id": event.message.message_id, "swarm_id": event.message.swarm_id,
            "sender_id": event.message.sender_id, "notification_level": event.notification_level.name.lower(),
        }
        async with httpx.AsyncClient(timeout=self._wake_timeout) as client:
            response = await client.post(self._wake_endpoint, json=payload)
            if response.status_code >= 400:
                raise WakeTriggerError(f"Wake endpoint returned {response.status_code}: {response.text}")

    async def _notify_callbacks(self, event: WakeEvent) -> None:
        """Notify all registered callbacks of the wake event."""
        for callback in self._callbacks:
            await callback(event)
