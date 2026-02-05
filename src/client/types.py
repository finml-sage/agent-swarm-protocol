"""Type definitions and enums for the Agent Swarm Protocol client library."""

from enum import Enum
from typing import TypedDict


class MessageType(str, Enum):
    MESSAGE = "message"
    SYSTEM = "system"
    NOTIFICATION = "notification"


class Priority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class ReferenceType(str, Enum):
    GITHUB_REPO = "github_repo"
    GITHUB_ISSUE = "github_issue"
    GITHUB_PR = "github_pr"
    GITHUB_COMMIT = "github_commit"
    URL = "url"


class ReferenceAction(str, Enum):
    CLAIMED = "claimed"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    UNBLOCKED = "unblocked"
    ASSIGNED = "assigned"
    MENTION = "mention"
    REVIEW_REQUESTED = "review_requested"


class AttachmentType(str, Enum):
    URL = "url"
    INLINE = "inline"


class SwarmSettings(TypedDict):
    allow_member_invite: bool
    require_approval: bool


class SwarmMember(TypedDict):
    agent_id: str
    endpoint: str
    public_key: str
    joined_at: str


class SwarmMembership(TypedDict):
    swarm_id: str
    name: str
    master: str
    members: list[SwarmMember]
    joined_at: str
    settings: SwarmSettings


class InviteTokenPayload(TypedDict, total=False):
    swarm_id: str
    master: str
    endpoint: str
    iat: int
    expires_at: str
    max_uses: int | None
