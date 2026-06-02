"""``aaaas-demo`` — run the bookkeeping agent against a seeded in-memory Odoo.

No API key, no Odoo, no network required. Demonstrates the full vertical:
3-way matching with confidence gating, an over-tolerance bill escalating to a
human, AR aging, bank reconciliation, and the daily summary.
"""
from __future__ import annotations

import argparse
from datetime import date

from .app import build_bookkeeper
from .config import PersonalityMode, Settings
from .hitl.interface import AutoApproveHITL
from .odoo.client import InMemoryBackend
from .seed import seed_demo_data


def _hr(title: str) -> None:
    print("\n" + "─" * 64)
    print(title)
    print("─" * 64)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AAAAS bookkeeping agent demo")
    parser.add_argument("--personality", choices=[m.value for m in PersonalityMode],
                        default="professional")
    args = parser.parse_args(argv)

    today = date(2026, 6, 2)
    settings = Settings.from_env()
    settings.personality = PersonalityMode(args.personality)
    settings.odoo.in_memory = True

    backend = InMemoryBackend()
    ids = seed_demo_data(backend, today=today)
    hitl = AutoApproveHITL()
    bk = build_bookkeeper(settings, backend=backend, hitl=hitl, today=today)

    ap = {t.name: t for t in bk.registry.all()}

    _hr("1. Auto-match a clean vendor bill (within tolerance)")
    r = ap["match_bill_to_po"].func(bill_id=ids["bill_clean"], po_ref="PO-2026-0089")
    print(f"  decision={r.decision.value}  ok={r.ok}  conf={r.confidence:.0%}")
    print(f"  {r.message}")

    _hr("2. Over-tolerance bill -> escalates to a human")
    r = ap["match_bill_to_po"].func(bill_id=ids["bill_variance"], po_ref="PO-2026-0090")
    print(f"  decision={r.decision.value}  ok={r.ok}  conf={r.confidence:.0%}")
    print(f"  {r.message}")
    print(f"  HITL requests seen: {len(hitl.seen)}")

    _hr("3. AR aging report")
    r = ap["generate_ar_aging_report"].func()
    for bucket, vals in r.data["buckets"].items():
        if vals["count"]:
            print(f"  {bucket:>7}: {vals['count']} invoice(s), {vals['amount']:,.2f}")
    print(f"  total outstanding: {r.data['total_outstanding']:,.2f}")

    _hr("4. Overdue invoices + reminders")
    r = ap["list_overdue_invoices"].func()
    for inv in r.data["overdue"]:
        print(f"  {inv['name']}  {inv['customer']:<14} {inv['days_overdue']:>3}d  {inv['residual']:,.2f}")
        ap["send_payment_reminder"].func(invoice_id=inv["id"])

    _hr("5. Bank reconciliation")
    r = ap["reconcile_bank_line"].func(bank_line_id=ids["bank_match"])
    print(f"  match: ok={r.ok} conf={r.confidence:.0%} — {r.message}")
    r = ap["reconcile_bank_line"].func(bank_line_id=ids["bank_orphan"])
    print(f"  orphan: ok={r.ok} conf={r.confidence:.0%} — {r.message}")

    _hr("6. Hard HITL — posting a bill always asks a human")
    r = ap["validate_vendor_bill"].func(bill_id=ids["bill_clean"])
    print(f"  ok={r.ok}  {r.message}")

    _hr("7. Daily summary to the finance team")
    r = ap["push_daily_summary"].func()
    print(f"  channel: {r.data['channel']}")
    print(f"  {r.data['rendered']}")

    _hr("Audit trail (Odoo chatter on the clean bill)")
    for note in backend.get_chatter("account.move", ids["bill_clean"]):
        print(f"  • {note}")

    print("\nDone. Every write was either auto (within policy) or human-approved.\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
