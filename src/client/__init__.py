"""Agent Swarm Protocol Python Client Library."""

from ._constants import PROTOCOL_VERSION
from .builder import MessageBuilder
from .client import SwarmClient
from .crypto import generate_keypair, public_key_from_base64, public_key_to_base64, sign_message, verify_signature
from .exceptions import NotMasterError, NotMemberError, RateLimitError, SignatureError, SwarmError, TokenError, TransportError
from .message import Message
from .tokens import generate_invite_token, parse_invite_token
from .types import AttachmentType, MessageType, Priority, ReferenceAction, ReferenceType, SwarmMember, SwarmMembership, SwarmSettings

__all__ = [
    "PROTOCOL_VERSION",
    "SwarmClient", "Message", "MessageBuilder",
    "generate_keypair", "sign_message", "verify_signature", "public_key_to_base64", "public_key_from_base64",
    "generate_invite_token", "parse_invite_token",
    "MessageType", "Priority", "AttachmentType", "ReferenceType", "ReferenceAction", "SwarmMember", "SwarmMembership", "SwarmSettings",
    "SwarmError", "SignatureError", "TransportError", "TokenError", "NotMasterError", "NotMemberError", "RateLimitError",
]

__version__ = PROTOCOL_VERSION
