"""Tests for message models and builder."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.client.builder import MessageBuilder
from src.client.message import Message, MessageSender
from src.client.types import AttachmentType, MessageType, Priority


class TestMessageSender:
    def test_valid_sender(self) -> None:
        s = MessageSender(agent_id="test", endpoint="https://example.com")
        assert s.agent_id == "test" and s.endpoint == "https://example.com"

    def test_invalid_endpoint_scheme(self) -> None:
        with pytest.raises(Exception):
            MessageSender(agent_id="test", endpoint="http://example.com")


class TestMessage:
    def test_message_defaults(self) -> None:
        m = Message(sender=MessageSender(agent_id="t", endpoint="https://x.com"), recipient="b", swarm_id=uuid4(), content="Hi")
        assert m.protocol_version == "0.1.0" and m.type == MessageType.MESSAGE and m.priority == Priority.NORMAL

    def test_message_to_wire_format(self) -> None:
        sid = uuid4()
        m = Message(sender=MessageSender(agent_id="t", endpoint="https://x.com"), recipient="r", swarm_id=sid, content="C", signature="s")
        w = m.to_wire_format()
        assert w["protocol_version"] == "0.1.0" and w["swarm_id"] == str(sid) and w["signature"] == "s"

    def test_message_optional_fields_excluded_when_default(self) -> None:
        w = Message(sender=MessageSender(agent_id="t", endpoint="https://x.com"), recipient="b", swarm_id=uuid4(), content="H").to_wire_format()
        assert "in_reply_to" not in w and "thread_id" not in w and "priority" not in w

    def test_message_parses_iso_timestamp(self) -> None:
        m = Message(sender=MessageSender(agent_id="t", endpoint="https://x.com"), recipient="b", swarm_id=uuid4(), content="H", timestamp="2026-02-05T14:30:00.000Z")
        assert m.timestamp.year == 2026 and m.timestamp.month == 2


class TestMessageBuilder:
    def test_builder_creates_valid_message(self) -> None:
        sid = uuid4()
        m = MessageBuilder("s", "https://s.com").to("r").in_swarm(sid).with_content("C").build()
        assert m.sender.agent_id == "s" and m.recipient == "r" and m.swarm_id == sid

    def test_builder_requires_recipient(self) -> None:
        with pytest.raises(ValueError, match="Recipient"):
            MessageBuilder("s", "https://s.com").in_swarm(uuid4()).with_content("C").build()

    def test_builder_requires_swarm_id(self) -> None:
        with pytest.raises(ValueError, match="Swarm ID"):
            MessageBuilder("s", "https://s.com").to("r").with_content("C").build()

    def test_builder_requires_content(self) -> None:
        with pytest.raises(ValueError, match="Content"):
            MessageBuilder("s", "https://s.com").to("r").in_swarm(uuid4()).build()

    def test_builder_sets_optional_fields(self) -> None:
        rt, th, ex = uuid4(), uuid4(), datetime(2026, 3, 1, tzinfo=timezone.utc)
        m = MessageBuilder("s", "https://s.com").to("r").in_swarm(uuid4()).with_content("C").as_type(MessageType.NOTIFICATION).with_priority(Priority.HIGH).replying_to(rt).in_thread(th).expires(ex).with_metadata("k", "v").build()
        assert m.type == MessageType.NOTIFICATION and m.priority == Priority.HIGH and m.in_reply_to == rt and m.thread_id == th

    def test_builder_adds_attachment(self) -> None:
        m = MessageBuilder("s", "https://s.com").to("r").in_swarm(uuid4()).with_content("C").attach(AttachmentType.INLINE, "text/plain", "data").build()
        assert m.attachments and len(m.attachments) == 1 and m.attachments[0].type == AttachmentType.INLINE
