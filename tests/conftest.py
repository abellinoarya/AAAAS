"""Shared fixtures: a seeded in-memory Odoo and a fully wired bookkeeper."""
from __future__ import annotations

from datetime import date

import pytest

from aaaas.app import build_bookkeeper
from aaaas.config import Settings
from aaaas.hitl.interface import AutoApproveHITL
from aaaas.odoo.client import InMemoryBackend
from aaaas.seed import seed_demo_data


@pytest.fixture
def today() -> date:
    return date(2026, 6, 2)


@pytest.fixture
def seeded(today):
    backend = InMemoryBackend()
    ids = seed_demo_data(backend, today=today)
    return backend, ids


@pytest.fixture
def bookkeeper(seeded, today):
    backend, ids = seeded
    settings = Settings()  # defaults: in-memory, professional, 3% tolerance
    hitl = AutoApproveHITL()
    bk = build_bookkeeper(settings, backend=backend, hitl=hitl, today=today)
    return bk, ids, hitl


@pytest.fixture
def tools(bookkeeper):
    bk, ids, hitl = bookkeeper
    return {t.name: t for t in bk.registry.all()}, ids, hitl, bk
