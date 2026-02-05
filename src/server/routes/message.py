"""POST /swarm/message endpoint handler."""
from typing import Union
from fastapi import APIRouter, Request, status
from src.server.models.requests import MessageRequest
from src.server.models.responses import MessageResponse, MessageQueuedResponse
from src.server.queue import MessageQueue


def create_message_router(queue: MessageQueue) -> APIRouter:
    """Create message router with injected dependencies."""
    router = APIRouter()

    @router.post(
        "/swarm/message",
        response_model=Union[MessageResponse, MessageQueuedResponse],
        status_code=status.HTTP_200_OK,
        tags=["messages"],
    )
    async def receive_message(request: Request, body: MessageRequest) -> Union[MessageResponse, MessageQueuedResponse]:
        """Receive a message from another agent."""
        queued = await queue.put(body)
        if queued:
            return MessageQueuedResponse(status="queued", message_id=body.message_id)
        return MessageResponse(status="received", message_id=body.message_id)

    return router
