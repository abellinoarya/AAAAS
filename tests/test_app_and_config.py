"""Composition root and configuration loading."""
from __future__ import annotations

from datetime import date

from aaaas.app import build_bookkeeper
from aaaas.config import PersonalityMode, Settings
from aaaas.hitl.interface import AutoApproveHITL
from aaaas.odoo.client import InMemoryBackend
from aaaas.seed import seed_demo_data


def test_settings_from_env_defaults():
    s = Settings.from_env(environ={})
    assert s.odoo.in_memory is True
    assert s.policy.price_variance_pct == 0.03
    assert s.personality == PersonalityMode.PROFESSIONAL


def test_settings_from_env_overrides():
    s = Settings.from_env(environ={
        "AAAAS_ODOO_IN_MEMORY": "false",
        "AAAAS_PRICE_VARIANCE_PCT": "0.05",
        "AAAAS_PAYMENT_HITL_LIMIT": "2500",
        "AAAAS_PERSONALITY": "genz",
        "AAAAS_CONF_AUTO": "0.95",
    })
    assert s.odoo.in_memory is False
    assert s.policy.price_variance_pct == 0.05
    assert s.policy.payment_hitl_limit == 2500
    assert s.personality == PersonalityMode.GENZ
    assert s.confidence.auto == 0.95


def test_invalid_personality_falls_back():
    s = Settings.from_env(environ={"AAAAS_PERSONALITY": "pirate"})
    assert s.personality == PersonalityMode.PROFESSIONAL


def test_build_bookkeeper_wires_everything():
    backend = InMemoryBackend()
    seed_demo_data(backend, today=date(2026, 6, 2))
    bk = build_bookkeeper(Settings(), backend=backend, hitl=AutoApproveHITL(),
                          today=date(2026, 6, 2))
    names = {t.name for t in bk.registry.all()}
    # A representative tool from each area is present.
    assert {"match_bill_to_po", "list_overdue_invoices", "reconcile_bank_line",
            "post_journal_entry", "generate_ar_aging_report"} <= names


def test_no_llm_configured_runs_without_crashing():
    backend = InMemoryBackend()
    seed_demo_data(backend, today=date(2026, 6, 2))
    # No API key -> _NullLLM. The agent should still return a result.
    bk = build_bookkeeper(Settings(), backend=backend, hitl=AutoApproveHITL(),
                          today=date(2026, 6, 2))
    result = bk.run("anything")
    assert result.done is True
