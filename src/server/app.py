"""FastAPI application factory."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from src.server.config import ServerConfig, load_config_from_env
from src.server.errors import SwarmProtocolError, RateLimitedError
from src.server.invoke_sdk import SdkInvokeConfig
from src.server.invoke_tmux import TmuxInvokeConfig
from src.server.invoker import AgentInvoker
from src.server.middleware.rate_limit import RateLimitMiddleware
from src.server.middleware.logging import RequestLoggingMiddleware
from src.server.models.responses import ErrorResponse, ErrorDetail
from src.server.queue import MessageQueue
from src.server.routes.message import create_message_router
from src.server.routes.join import create_join_router
from src.server.routes.health import create_health_router
from src.server.routes.info import create_info_router
from src.server.routes.wake import create_wake_router
from src.state.database import DatabaseManager
from src.claude.notification_preferences import NotificationPreferences
from src.claude.session_manager import SessionManager
from src.claude.wake_trigger import WakeTrigger

logger = logging.getLogger(__name__)


def _build_wake_trigger(
    config: ServerConfig,
    db_manager: DatabaseManager,
) -> Optional[WakeTrigger]:
    """Build a WakeTrigger when wake config is enabled, else return None."""
    if not config.wake.enabled:
        return None
    return WakeTrigger(
        db_manager=db_manager,
        wake_endpoint=config.wake.endpoint,
        preferences=NotificationPreferences(),
        wake_timeout=config.wake.timeout,
    )


def _build_invoker(config: ServerConfig) -> AgentInvoker:
    """Build an AgentInvoker from the wake endpoint configuration."""
    wep = config.wake_endpoint
    sdk_config = None
    tmux_config = None
    if wep.invoke_method == "sdk":
        sdk_config = SdkInvokeConfig(
            cwd=wep.sdk_cwd,
            permission_mode=wep.sdk_permission_mode,
            max_turns=wep.sdk_max_turns,
            model=wep.sdk_model,
        )
    if wep.invoke_method == "tmux":
        tmux_config = TmuxInvokeConfig(tmux_target=wep.tmux_target)
    return AgentInvoker(
        method=wep.invoke_method,
        target=wep.invoke_target,
        sdk_config=sdk_config,
        tmux_config=tmux_config,
    )


def create_app(config: Optional[ServerConfig] = None) -> FastAPI:
    """Create and configure the FastAPI application.

    When called without arguments (e.g. via uvicorn --factory), loads
    configuration from environment variables.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    if config is None:
        config = load_config_from_env()

    db_manager = DatabaseManager(config.db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await db_manager.initialize()
        logger.info("Database initialized at %s", config.db_path)

        wake_trigger = _build_wake_trigger(config, db_manager)
        if wake_trigger is not None:
            logger.info(
                "WakeTrigger active, endpoint=%s", config.wake.endpoint,
            )
        else:
            logger.info("WakeTrigger disabled")

        app.state.wake_trigger = wake_trigger
        yield
        await db_manager.close()

    app = FastAPI(
        title="Agent Swarm Protocol",
        description="P2P communication server for autonomous agents",
        version=config.agent.protocol_version,
        lifespan=lifespan,
    )
    queue = MessageQueue(max_size=config.queue_max_size)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RateLimitMiddleware, requests_per_minute=config.rate_limit.messages_per_minute)
    app.add_exception_handler(SwarmProtocolError, _protocol_error_handler)
    app.add_exception_handler(ValidationError, _validation_error_handler)
    app.include_router(create_message_router(queue, db_manager))
    app.include_router(create_join_router(config, db_manager))
    app.include_router(create_health_router(config, queue))
    app.include_router(create_info_router(config))

    # Wire /api/wake endpoint when enabled
    if config.wake_endpoint.enabled:
        session_mgr = SessionManager(
            session_file=Path(config.wake_endpoint.session_file),
            session_timeout_minutes=config.wake_endpoint.session_timeout_minutes,
        )
        invoker = _build_invoker(config)
        app.include_router(
            create_wake_router(
                session_manager=session_mgr,
                invoker=invoker,
                wake_secret=config.wake_endpoint.secret,
                db_manager=db_manager,
                session_timeout_minutes=config.wake_endpoint.session_timeout_minutes,
            )
        )
        logger.info(
            "Wake endpoint active, method=%s", config.wake_endpoint.invoke_method,
        )
    else:
        logger.info("Wake endpoint disabled")

    return app


async def _protocol_error_handler(request: Request, exc: SwarmProtocolError) -> JSONResponse:
    headers = {}
    if isinstance(exc, RateLimitedError) and exc.reset_time:
        headers["Retry-After"] = str(exc.reset_time)
    response = ErrorResponse(error=ErrorDetail(code=exc.error_code, message=exc.message, details=exc.details))
    return JSONResponse(status_code=exc.status_code, content=response.model_dump(), headers=headers if headers else None)


async def _validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    response = ErrorResponse(error=ErrorDetail(code="INVALID_FORMAT", message="Request validation failed", details={"validation_errors": exc.errors()}))
    return JSONResponse(status_code=400, content=response.model_dump())
