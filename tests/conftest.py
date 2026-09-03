"""Hermetic defaults for the suite.

Production now defaults the catalog overlay to ~/.drift/catalog when $DRIFT_CATALOG_DIR
is unset. Tests must NOT load a developer's real overlay (client hosts, resolve verdicts)
unless they opt in with a tmp path. Empty $DRIFT_CATALOG_DIR disables the overlay.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_catalog_overlay(monkeypatch):
    monkeypatch.setenv("DRIFT_CATALOG_DIR", "")


@pytest.fixture(autouse=True)
def _no_update_check(monkeypatch):
    """`cli.main()` now runs a published-version check on every invocation. The suite calls
    main() well over a thousand times; without this it would make a network request per call
    and the run would be neither hermetic nor fast. Tests that exercise the check opt back in
    by deleting this var themselves."""
    monkeypatch.setenv("DRIFT_NO_UPDATE_CHECK", "1")
