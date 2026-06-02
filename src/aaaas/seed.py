"""Deterministic demo/test data for the in-memory Odoo backend.

Seeds a small but realistic book: vendors, customers, purchase orders, vendor
bills (one clean match, one over-tolerance), open customer invoices across
aging buckets, and matching/non-matching bank lines. Used by both the demos
and the test suite so behaviour is reproducible.
"""
from __future__ import annotations

from datetime import date, timedelta

from .odoo.client import InMemoryBackend


def seed_demo_data(backend: InMemoryBackend, today: date | None = None) -> dict:
    """Populate ``backend`` and return a dict of the key record ids."""
    today = today or date(2026, 6, 2)
    ids: dict[str, int] = {}

    # ---- partners ----
    abc = backend.insert("res.partner", {"name": "ABC Supplies"})
    globex = backend.insert("res.partner", {"name": "Globex Trading"})
    initech = backend.insert("res.partner", {"name": "Initech LLC"})
    umbrella = backend.insert("res.partner", {"name": "Umbrella Corp"})
    ids.update(vendor_abc=abc, vendor_globex=globex, cust_initech=initech, cust_umbrella=umbrella)

    # ---- purchase orders ----
    po_clean = backend.insert("purchase.order", {
        "name": "PO-2026-0089", "partner_id": [abc, "ABC Supplies"],
        "amount_total": 5000.0, "state": "purchase",
    })
    backend.insert("purchase.order.line", {
        "order_id": po_clean, "product_id": [1, "Widget A"],
        "product_qty": 100, "price_unit": 50.0, "price_subtotal": 5000.0,
    })
    po_variance = backend.insert("purchase.order", {
        "name": "PO-2026-0090", "partner_id": [globex, "Globex Trading"],
        "amount_total": 2000.0, "state": "purchase",
    })
    backend.insert("purchase.order.line", {
        "order_id": po_variance, "product_id": [2, "Gadget B"],
        "product_qty": 40, "price_unit": 50.0, "price_subtotal": 2000.0,
    })
    ids.update(po_clean=po_clean, po_variance=po_variance)

    # ---- vendor bills ----
    # Clean: equals its PO exactly -> should auto-match.
    bill_clean = backend.insert("account.move", {
        "move_type": "in_invoice", "name": "BILL/2026/0042",
        "partner_id": [abc, "ABC Supplies"], "ref": "ABC-INV-7781",
        "amount_total": 5000.0, "state": "draft",
        "invoice_date": today.isoformat(),
        "invoice_date_due": (today + timedelta(days=30)).isoformat(),
        "purchase_id": False,
    })
    # Over-tolerance: 4% above its PO -> should escalate to a human.
    bill_variance = backend.insert("account.move", {
        "move_type": "in_invoice", "name": "BILL/2026/0043",
        "partner_id": [globex, "Globex Trading"], "ref": "GBX-5521",
        "amount_total": 2080.0, "state": "draft",
        "invoice_date": today.isoformat(),
        "invoice_date_due": (today + timedelta(days=15)).isoformat(),
        "purchase_id": False,
    })
    ids.update(bill_clean=bill_clean, bill_variance=bill_variance)

    # ---- customer invoices across aging buckets ----
    inv_current = backend.insert("account.move", {
        "move_type": "out_invoice", "name": "INV/2026/0101",
        "partner_id": [initech, "Initech LLC"], "amount_total": 1200.0,
        "amount_residual": 1200.0, "state": "posted",
        "invoice_date_due": (today + timedelta(days=10)).isoformat(),
    })
    inv_30 = backend.insert("account.move", {
        "move_type": "out_invoice", "name": "INV/2026/0098",
        "partner_id": [initech, "Initech LLC"], "amount_total": 800.0,
        "amount_residual": 800.0, "state": "posted",
        "invoice_date_due": (today - timedelta(days=20)).isoformat(),
    })
    inv_90 = backend.insert("account.move", {
        "move_type": "out_invoice", "name": "INV/2026/0071",
        "partner_id": [umbrella, "Umbrella Corp"], "amount_total": 3400.0,
        "amount_residual": 3400.0, "state": "posted",
        "invoice_date_due": (today - timedelta(days=95)).isoformat(),
    })
    ids.update(inv_current=inv_current, inv_30=inv_30, inv_90=inv_90)

    # ---- bank lines ----
    # Exact amount + matching payer for inv_30 -> high-confidence reconcile.
    bank_match = backend.insert("account.bank.statement.line", {
        "date": today.isoformat(), "amount": 800.0,
        "partner_id": [initech, "Initech LLC"], "payment_ref": "INV/2026/0098",
        "is_reconciled": False,
    })
    # Odd amount, unknown payer -> no confident match.
    bank_orphan = backend.insert("account.bank.statement.line", {
        "date": today.isoformat(), "amount": 123.45,
        "partner_id": False, "payment_ref": "MISC", "is_reconciled": False,
    })
    ids.update(bank_match=bank_match, bank_orphan=bank_orphan)

    # ---- recurring journal template ----
    tmpl = backend.insert("account.move", {
        "move_type": "entry", "name": "RENT-ACCRUAL", "ref": "Monthly rent accrual",
        "amount_total": 2500.0, "state": "draft", "aaaas_recurring": True,
    })
    ids.update(recurring_template=tmpl)

    return ids
