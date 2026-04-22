"""Regression tests for package-integrity startup checks.

Guards against reintroducing the 2026-04-22 failure mode where a
PyPI distribution-name/module-name collision silently installs the
wrong package and crashes the handler at runtime instead of the
server at boot. See src/server/_integrity.py and
agent-swarm-protocol#193.
"""
from __future__ import annotations

import sys
import types

import pytest

from src.server import _integrity


def test_verify_accepts_real_python_toon() -> None:
    """Happy path — the CHECKED-IN environment must pass the guard.

    If this test ever fails in CI or on a fresh venv, the venv does
    NOT have python-toon installed correctly — which means the server
    would have crashed at first message anyway. Catching it here
    makes the failure mode obvious at test time instead of at
    production traffic time.
    """
    _integrity.verify_package_integrity()


def test_verify_rejects_wrong_toon(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub a fake ``toon`` module lacking ``encode`` and assert the
    guard raises with the fix shipped in the error message."""
    fake_toon = types.ModuleType("toon")
    fake_toon.__file__ = "/tmp/fake/toon/__init__.py"
    monkeypatch.setitem(sys.modules, "toon", fake_toon)

    with pytest.raises(RuntimeError) as excinfo:
        _integrity.verify_package_integrity()

    msg = str(excinfo.value)
    assert "toon" in msg
    assert "python-toon" in msg
    assert "pip uninstall" in msg
    assert "pip install" in msg
    # ensures the file path is surfaced so the operator sees which
    # install shadowed the real dependency
    assert "/tmp/fake/toon" in msg


def test_verify_rejects_missing_attr_on_registered_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any future package added to ``_REQUIRED_PACKAGE_SHAPES`` gets
    the same fail-loud behavior. Stub a synthetic shape end-to-end to
    guarantee that property without pinning it to ``toon``."""
    fake_pkg = types.ModuleType("synthetic_probe_pkg")
    fake_pkg.__file__ = "/tmp/fake/synthetic_probe_pkg.py"
    monkeypatch.setitem(sys.modules, "synthetic_probe_pkg", fake_pkg)
    monkeypatch.setattr(
        _integrity,
        "_REQUIRED_PACKAGE_SHAPES",
        [("synthetic_probe_pkg", "required_fn", "real-synthetic>=1.0")],
    )

    with pytest.raises(RuntimeError, match="real-synthetic>=1.0"):
        _integrity.verify_package_integrity()
