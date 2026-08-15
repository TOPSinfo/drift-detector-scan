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
