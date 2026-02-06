"""Tests for exception types."""

import pytest

from src.client.exceptions import NotMasterError, NotMemberError, RateLimitError
from src.client.exceptions import SignatureError, SwarmError, TokenError
from src.client.exceptions import TransportError


class TestExceptionHierarchy:
    def test_all_exceptions_inherit_from_swarm_error(self) -> None:
        for exc in (SignatureError, TransportError,
                    TokenError, NotMasterError, NotMemberError):
            assert issubclass(exc, SwarmError)

    def test_rate_limit_error_inherits_from_transport_error(self) -> None:
        assert issubclass(RateLimitError, TransportError)


class TestTransportError:
    def test_transport_error_stores_status_code(self) -> None:
        e = TransportError("fail", status_code=500)
        assert e.status_code == 500
        assert str(e) == "fail"

    def test_transport_error_status_code_optional(self) -> None:
        assert TransportError("fail").status_code is None


class TestRateLimitError:
    def test_rate_limit_error_stores_all_fields(self) -> None:
        e = RateLimitError("limited", retry_after=60, limit=100, remaining=0, reset_at=1738765860)
        assert e.status_code == 429
        assert e.retry_after == 60
        assert e.limit == 100
        assert e.remaining == 0
        assert e.reset_at == 1738765860

    def test_rate_limit_error_fields_optional(self) -> None:
        e = RateLimitError("limited")
        assert e.retry_after is None
        assert e.limit is None


class TestCatchingExceptions:
    def test_catch_specific_exception(self) -> None:
        with pytest.raises(TokenError):
            raise TokenError("expired")

    def test_catch_as_swarm_error(self) -> None:
        exceptions = [
            SignatureError("s"),
            TransportError("t"),
            TokenError("t"),
            NotMasterError("m"),
            NotMemberError("m"),
            RateLimitError("r"),
        ]
        for exc in exceptions:
            try:
                raise exc
            except SwarmError as e:
                assert e is exc
