"""Accounts-payable tools, including the policy gating and audit trail."""
from __future__ import annotations

from aaaas.agent.confidence import Decision
from aaaas.app import build_bookkeeper
from aaaas.config import Settings
from aaaas.hitl.interface import AutoApproveHITL, AutoRejectHITL


def test_clean_bill_auto_matches(tools):
    t, ids, hitl, bk = tools
    r = t["match_bill_to_po"].func(bill_id=ids["bill_clean"], po_ref="PO-2026-0089")
    assert r.ok is True
    assert r.decision == Decision.AUTO
    assert r.confidence >= 0.9
    # No human was needed.
    assert hitl.seen == []
    # The bill is now linked to the PO in Odoo.
    bill = bk.client.read("account.move", [ids["bill_clean"]], fields=["purchase_id"])[0]
    assert bill["purchase_id"] == ids["po_clean"]


def test_over_tolerance_bill_routes_to_human(tools):
    t, ids, hitl, bk = tools
    r = t["match_bill_to_po"].func(bill_id=ids["bill_variance"], po_ref="PO-2026-0090")
    assert r.decision == Decision.DRAFT_HITL
    # AutoApprove channel was consulted exactly once.
    assert len(hitl.seen) == 1
    assert hitl.seen[0].action == "match_bill_to_po"


def test_over_tolerance_bill_blocked_when_human_rejects(seeded, today):
    backend, ids = seeded
    bk = build_bookkeeper(Settings(), backend=backend, hitl=AutoRejectHITL(), today=today)
    t = {x.name: x for x in bk.registry.all()}
    r = t["match_bill_to_po"].func(bill_id=ids["bill_variance"], po_ref="PO-2026-0090")
    assert r.ok is False
    # Rejected -> the bill must NOT have been linked.
    bill = bk.client.read("account.move", [ids["bill_variance"]], fields=["purchase_id"])[0]
    assert not bill["purchase_id"]


def test_validate_vendor_bill_is_hard_hitl(seeded, today):
    backend, ids = seeded
    # Even at 99% competence, a rejection must block posting.
    bk = build_bookkeeper(Settings(), backend=backend, hitl=AutoRejectHITL(), today=today)
    t = {x.name: x for x in bk.registry.all()}
    r = t["validate_vendor_bill"].func(bill_id=ids["bill_clean"])
    assert r.ok is False
    state = bk.client.read("account.move", [ids["bill_clean"]], fields=["state"])[0]["state"]
    assert state == "draft"  # never posted without approval


def test_validate_vendor_bill_posts_after_approval(tools):
    t, ids, hitl, bk = tools
    r = t["validate_vendor_bill"].func(bill_id=ids["bill_clean"])
    assert r.ok is True
    state = bk.client.read("account.move", [ids["bill_clean"]], fields=["state"])[0]["state"]
    assert state == "posted"


def test_match_writes_audit_note(tools):
    t, ids, hitl, bk = tools
    t["match_bill_to_po"].func(bill_id=ids["bill_clean"], po_ref="PO-2026-0089")
    chatter = bk.context.client.backend.get_chatter("account.move", ids["bill_clean"])
    assert any("matched bill to PO" in note for note in chatter)


def test_code_expense_line_uses_learned_pattern(tools):
    t, ids, hitl, bk = tools
    vendor = ids["vendor_abc"]
    # Teach the memory: this vendor codes to account 5010.
    for _ in range(5):
        bk.context.memory.record_coding(vendor, 5010)
    line_id = bk.client.create("account.move.line", {"move_id": ids["bill_clean"]})
    r = t["code_expense_line"].func(line_id=line_id, vendor_id=vendor, account_id=5010)
    assert r.ok is True
    assert r.decision == Decision.AUTO  # learned pattern -> high confidence
