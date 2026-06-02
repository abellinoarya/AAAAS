"""AR, bank reconciliation, and reporting tools."""
from __future__ import annotations

from aaaas.agent.confidence import Decision


def test_list_overdue_invoices(tools):
    t, ids, hitl, bk = tools
    r = t["list_overdue_invoices"].func()
    names = {o["name"] for o in r.data["overdue"]}
    assert "INV/2026/0098" in names  # 20 days overdue
    assert "INV/2026/0071" in names  # 95 days overdue
    assert "INV/2026/0101" not in names  # not yet due


def test_recent_reminder_auto_old_reminder_escalates(tools):
    t, ids, hitl, bk = tools
    # 20 days overdue -> within auto window.
    r = t["send_payment_reminder"].func(invoice_id=ids["inv_30"])
    assert r.decision == Decision.AUTO
    # 95 days overdue -> external + judgment -> hard HITL (consulted human).
    before = len(hitl.seen)
    r2 = t["send_payment_reminder"].func(invoice_id=ids["inv_90"])
    assert len(hitl.seen) == before + 1


def test_bank_reconcile_exact_match(tools):
    t, ids, hitl, bk = tools
    r = t["reconcile_bank_line"].func(bank_line_id=ids["bank_match"])
    assert r.ok is True
    assert r.confidence >= 0.9
    assert r.decision == Decision.AUTO
    # The invoice residual was cleared and the line marked reconciled.
    inv = bk.client.read("account.move", [ids["inv_30"]], fields=["amount_residual"])[0]
    assert inv["amount_residual"] == 0.0
    line = bk.client.read(
        "account.bank.statement.line", [ids["bank_match"]], fields=["is_reconciled"])[0]
    assert line["is_reconciled"] is True


def test_bank_orphan_line_pauses(tools):
    t, ids, hitl, bk = tools
    r = t["reconcile_bank_line"].func(bank_line_id=ids["bank_orphan"])
    assert r.ok is False
    # Low confidence -> paused -> surfaced in the daily notices.
    assert any("reconcile_bank_line" in n for n in bk.context.notices)


def test_ar_aging_report_buckets(tools):
    t, ids, hitl, bk = tools
    r = t["generate_ar_aging_report"].func()
    buckets = r.data["buckets"]
    assert buckets["1-30"]["amount"] == 800.0
    assert buckets["90+"]["amount"] == 3400.0
    assert r.data["total_outstanding"] == 5400.0


def test_daily_summary_collects_notices(tools):
    t, ids, hitl, bk = tools
    # Force a paused item into the notices.
    t["reconcile_bank_line"].func(bank_line_id=ids["bank_orphan"])
    r = t["push_daily_summary"].func()
    assert r.data["channel"] == "#finance"
    assert r.data["items"]  # non-empty


def test_cash_position(tools):
    t, ids, hitl, bk = tools
    r = t["summarize_cash_position"].func()
    assert r.data["receivable"] > 0
    assert "net" in r.data
