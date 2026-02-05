"""Route handlers for swarm protocol endpoints."""
from src.server.routes.message import create_message_router
from src.server.routes.join import create_join_router
from src.server.routes.health import create_health_router
from src.server.routes.info import create_info_router
from src.server.routes.wake import create_wake_router
__all__ = [
    "create_message_router",
    "create_join_router",
    "create_health_router",
    "create_info_router",
    "create_wake_router",
]
