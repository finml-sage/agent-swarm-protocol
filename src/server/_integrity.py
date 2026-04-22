"""Startup package-integrity checks.

Guards against a class of dependency failures where a PyPI distribution
name differs from its Python module name, and pip has silently resolved
the module name to a squatted or unrelated package. The wrong package
imports cleanly but crashes at runtime on the first call that uses an
attribute only the correct package provides.

Concrete trigger: 2026-04-22 incident. ``pyproject.toml`` declares
``python-toon>=0.1.3`` (provides ``toon.encode()``). A reactive
``pip install toon`` resolved to the unrelated ``toon`` package
(neuroscience tooling, no ``encode``). ``import toon`` succeeded at
boot; first inbound POST to ``/swarm/message`` raised
``AttributeError: module 'toon' has no attribute 'encode'`` and
FastAPI returned 500 with an empty body. See
agent-swarm-protocol#193 and kelvin's memory entry
``kelvin/atlas/pypi-dist-vs-module-name-trap.md``.

This module fails the server LOUDLY at import time, with an error
message that ships the fix to the operator. Generalizes to any
dist/module-name collision — add a new tuple to
``_REQUIRED_PACKAGE_SHAPES`` as new dependencies with collision risk
land (``dateutil``/``python-dateutil``, ``yaml``/``pyyaml``,
``bs4``/``beautifulsoup4``, ``dotenv``/``python-dotenv`` are the
common wild examples).
"""
from __future__ import annotations

import importlib
import importlib.metadata
import logging

logger = logging.getLogger(__name__)

# (module_name, expected_attr, pip_spec_for_correct_dist)
#
# Add a row here when a new dependency with dist/module-name-collision
# risk lands in pyproject.toml. Choose an ``expected_attr`` that the
# CORRECT package provides and that a plausibly-squatted package with
# the same module name would not. Prefer a method you actually call at
# runtime — that way the assertion fails for the same reason the real
# handler would.
_REQUIRED_PACKAGE_SHAPES: list[tuple[str, str, str]] = [
    ("toon", "encode", "python-toon>=0.1.3"),
]


def verify_package_integrity() -> None:
    """Raise ``RuntimeError`` if any required package resolves to the wrong distribution.

    Called once at module import time from ``src/server/app.py``.
    Runs under any launcher (uvicorn, pytest, ad-hoc), not only under a
    specific systemd unit. The error message includes the resolved
    distribution name, the module ``__file__``, and the exact pip
    commands to fix — so the next operator hitting this does not need
    to find this code.
    """
    for module_name, expected_attr, correct_spec in _REQUIRED_PACKAGE_SHAPES:
        mod = importlib.import_module(module_name)
        if hasattr(mod, expected_attr):
            continue

        try:
            resolved = importlib.metadata.distribution(module_name).metadata["Name"]
        except importlib.metadata.PackageNotFoundError:
            resolved = "unknown"

        mod_path = getattr(mod, "__file__", "<unknown>")
        raise RuntimeError(
            f"Wrong '{module_name}' package installed at {mod_path} "
            f"(dist: {resolved}); expected {correct_spec}. "
            f"Fix: pip uninstall -y {module_name} && "
            f"pip install '{correct_spec}'"
        )

    logger.info(
        "Package integrity verified: %d required shape(s) resolved correctly.",
        len(_REQUIRED_PACKAGE_SHAPES),
    )
