"""The initiative engine: scheduled jobs and event handling."""
from __future__ import annotations

from aaaas.agent.brain import Agent, FakeLLM
from aaaas.app import build_bookkeeper
from aaaas.config import Settings
from aaaas.hitl.interface import AutoApproveHITL
from aaaas.initiative import EventRule, InitiativeEngine, DEFAULT_SCHEDULE


def _engine(seeded, today):
    backend, ids = seeded
    fake = FakeLLM([])  # ends each run immediately; we test routing, not reasoning
    bk = build_bookkeeper(Settings(), backend=backend, hitl=AutoApproveHITL(),
                          today=today, llm=fake)
    return InitiativeEngine(Agent(fake, bk.registry))


def test_due_jobs_match_time(seeded, today):
    engine = _engine(seeded, today)
    due = engine.due_jobs(8, 0)
    assert [j.name for j in due] == ["ar_aging"]
    assert engine.due_jobs(3, 33) == []


def test_run_due_invokes_agent(seeded, today):
    engine = _engine(seeded, today)
    results = engine.run_due(17, 30)  # daily_summary
    assert len(results) == 1
    name, run = results[0]
    assert name == "daily_summary"
    assert run.done is True


def test_event_routing(seeded, today):
    engine = _engine(seeded, today)
    results = engine.handle_event("vendor_bill.created", {"id": 42})
    assert len(results) == 1
    assert results[0][0] == "vendor_bill.created"


def test_event_rule_render_handles_missing_keys():
    rule = EventRule("x", "bill {id} arrived")
    assert rule.render({"id": 7}) == "bill 7 arrived"
    assert rule.render({}) == "bill {id} arrived"  # graceful, no crash


def test_default_schedule_is_sane():
    names = {j.name for j in DEFAULT_SCHEDULE}
    assert {"ar_aging", "ap_due", "bank_recon", "daily_summary"} <= names
