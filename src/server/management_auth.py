"""Authentication dependency for private management API routes."""

from secrets import compare_digest
from typing import Annotated, Awaitable, Callable

from fastapi import Header, HTTPException, status

ManagementAuthDependency = Callable[..., Awaitable[None]]


def create_management_auth_dependency(
    expected_token: str,
) -> ManagementAuthDependency:
    """Create a fail-closed Bearer-token dependency for management routes."""
    if not expected_token:
        raise ValueError("Management API token must not be empty")

    async def require_management_auth(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        scheme, separator, credentials = (authorization or "").partition(" ")
        is_authorized = (
            separator == " "
            and scheme.lower() == "bearer"
            and bool(credentials)
            and compare_digest(credentials, expected_token)
        )
        if not is_authorized:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid management API Bearer token required",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return require_management_auth
