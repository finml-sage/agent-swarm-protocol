"""FastAPI application factory."""
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from src.server.config import ServerConfig, load_config_from_env
from src.server.errors import SwarmProtocolError, RateLimitedError
from src.server.middleware.rate_limit import RateLimitMiddleware
from src.server.middleware.logging import RequestLoggingMiddleware
from src.server.models.responses import ErrorResponse, ErrorDetail
from src.server.queue import MessageQueue
from src.server.routes.message import create_message_router
from src.server.routes.join import create_join_router
from src.server.routes.health import create_health_router
from src.server.routes.info import create_info_router
from src.state.database import DatabaseManager

logger = logging.getLogger(__name__)


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
