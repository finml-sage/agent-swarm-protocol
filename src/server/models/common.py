"""Common model types shared across requests and responses."""
from typing import Annotated
from pydantic import BaseModel, Field, field_validator


class Sender(BaseModel):
    agent_id: Annotated[str, Field(min_length=1)]
    endpoint: Annotated[str, Field()]

    @field_validator("endpoint")
    @classmethod
    def validate_https_endpoint(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("Endpoint must use HTTPS")
        return v


class JoinSender(BaseModel):
    agent_id: Annotated[str, Field(min_length=1)]
    endpoint: Annotated[str, Field()]
    public_key: Annotated[str, Field()]

    @field_validator("endpoint")
    @classmethod
    def validate_https_endpoint(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("Endpoint must use HTTPS")
        return v


class Member(BaseModel):
    agent_id: Annotated[str, Field()]
    endpoint: Annotated[str, Field()]
    public_key: Annotated[str, Field()]
