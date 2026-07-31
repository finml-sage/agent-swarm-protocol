"""Access-control tests for the private inbox/outbox management API."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.server.app import create_app
from src.server.config import (
    AgentConfig,
    ManagementApiConfig,
    ServerConfig,
    WakeConfig,
    WakeEndpointConfig,
    load_config_from_env,
)

_TOKEN = "test-management-token"


def _config(
    agent: AgentConfig,
    db_path: Path,
    *,
    enabled: bool = True,
) -> ServerConfig:
    return ServerConfig(
        agent=agent,
        db_path=db_path,
        management_api=ManagementApiConfig(enabled=enabled, token=_TOKEN),
        wake=WakeConfig(enabled=False, endpoint=""),
        wake_endpoint=WakeEndpointConfig(enabled=False),
    )


@pytest.mark.parametrize("path", ["/api/inbox", "/api/outbox"])
@pytest.mark.parametrize(
    "authorization",
    [None, "", "Basic dGVzdDp0ZXN0", "Bearer", "Bearer wrong-token"],
)
def test_private_routes_reject_invalid_authorization(
    agent_config: AgentConfig,
    tmp_path: Path,
    path: str,
    authorization: str | None,
) -> None:
    headers = {"Authorization": authorization} if authorization else {}
    with TestClient(create_app(_config(agent_config, tmp_path / "auth.db"))) as client:
        response = client.get(path, headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert set(response.json()) == {"detail"}


@pytest.mark.parametrize("path", ["/api/inbox", "/api/outbox"])
def test_private_routes_accept_valid_bearer_token(
    agent_config: AgentConfig,
    tmp_path: Path,
    path: str,
) -> None:
    with TestClient(create_app(_config(agent_config, tmp_path / "valid.db"))) as client:
        response = client.get(
            path,
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )

    assert response.status_code == 200
    assert response.json() == {"count": 0, "messages": []}


@pytest.mark.parametrize("path", ["/api/inbox", "/api/outbox"])
def test_private_routes_are_absent_when_disabled(
    agent_config: AgentConfig,
    tmp_path: Path,
    path: str,
) -> None:
    with TestClient(
        create_app(_config(agent_config, tmp_path / "disabled.db", enabled=False))
    ) as client:
        response = client.get(path)

    assert response.status_code == 404


def test_enabled_management_api_requires_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_ID", "test-agent")
    monkeypatch.setenv("AGENT_ENDPOINT", "https://test.example.com/swarm")
    monkeypatch.setenv("AGENT_PUBLIC_KEY", "test-public-key")
    monkeypatch.setenv("MANAGEMENT_API_ENABLED", "true")
    monkeypatch.delenv("MANAGEMENT_API_TOKEN", raising=False)

    with pytest.raises(ValueError, match="MANAGEMENT_API_TOKEN required"):
        load_config_from_env()
