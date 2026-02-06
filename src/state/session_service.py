"""SDK session persistence service for conversation continuity.

Provides convenience functions for looking up and persisting SDK session
IDs via the SessionRepository.  Used by the wake endpoint to resume
conversations with the same sender/swarm pair.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from src.state.database import DatabaseManager
from src.state.models.session import SdkSession
from src.state.repositories.sessions import SessionRepository

logger = logging.getLogger(__name__)


async def lookup_sdk_session(
    db_manager: DatabaseManager,
    swarm_id: str,
    peer_id: str,
    timeout_minutes: int,
) -> Optional[str]:
    """Look up a non-expired SDK session for conversation continuity.

    Args:
        db_manager: Database connection manager.
        swarm_id: The swarm the conversation belongs to.
        peer_id: The remote agent in the conversation.
        timeout_minutes: Maximum idle time before session expires.

    Returns:
        The session_id string if a valid session exists, None otherwise.
    """
    try:
        async with db_manager.connection() as conn:
            repo = SessionRepository(conn)
            session = await repo.get_active(swarm_id, peer_id, timeout_minutes)
            if session is not None:
                logger.info(
                    "Resuming SDK session=%s for swarm=%s peer=%s",
                    session.session_id, swarm_id, peer_id,
                )
                return session.session_id
    except Exception as exc:
        logger.warning("Failed to look up SDK session: %s", exc)
    return None


async def persist_sdk_session(
    db_manager: DatabaseManager,
    swarm_id: str,
    peer_id: str,
    session_id: str,
) -> None:
    """Persist the SDK session_id for future conversation continuity.

    Fire-and-forget: failures are logged as warnings but never block
    the calling operation.

    Args:
        db_manager: Database connection manager.
        swarm_id: The swarm the conversation belongs to.
        peer_id: The remote agent in the conversation.
        session_id: The SDK session identifier to persist.
    """
    try:
        async with db_manager.connection() as conn:
            repo = SessionRepository(conn)
            sdk_session = SdkSession(
                swarm_id=swarm_id,
                peer_id=peer_id,
                session_id=session_id,
                last_active=datetime.now(timezone.utc),
            )
            await repo.upsert(sdk_session)
            logger.info(
                "Persisted SDK session=%s for swarm=%s peer=%s",
                session_id, swarm_id, peer_id,
            )
    except Exception as exc:
        logger.warning("Failed to persist SDK session: %s", exc)
