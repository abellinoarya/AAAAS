"""Pure financial logic — the deterministic core."""
from __future__ import annotations

from datetime import date

import pytest

from aaaas.logic import (
    aging_bucket,
    best_bank_match,
    bank_match_score,
    confidence_from_variance,
    summarize_aging,
    three_way_match,
)
from aaaas.odoo.models import BankLine, CustomerInvoice, PurchaseOrder, VendorBill


def _bill(total):
    return VendorBill(1, "B", 1, "ABC", "ref", total, "draft", None, None, None)


def _po(total):
    return PurchaseOrder(1, "PO-1", 1, "ABC", total, "purchase")


def test_confidence_decreases_with_variance():
    t = 0.03
    assert confidence_from_variance(0.0, t) == 0.99
    seq = [confidence_from_variance(v, t) for v in (0.0, 0.005, 0.02, 0.05, 0.1, 0.5)]
    assert seq == sorted(seq, reverse=True)  # monotonically non-increasing


def test_three_way_match_within_tolerance():
    r = three_way_match(_bill(5000), _po(5000), 0.03)
    assert r.matched is True
    assert r.variance_pct == 0.0
    assert r.confidence >= 0.9


def test_three_way_match_over_tolerance():
    r = three_way_match(_bill(2080), _po(2000), 0.03)
    assert r.matched is False
    assert round(r.variance_pct, 4) == 0.04
    assert r.confidence < 0.9
    assert "exceeds" in r.reason


def test_three_way_match_zero_value_po():
    r = three_way_match(_bill(100), _po(0), 0.03)
    assert r.matched is False


@pytest.mark.parametrize("delta_days,expected", [
    (-5, "current"), (0, "current"), (10, "1-30"), (45, "31-60"),
    (75, "61-90"), (200, "90+"),
])
def test_aging_buckets(delta_days, expected):
    today = date(2026, 6, 2)
    due = date.fromordinal(today.toordinal() - delta_days)
    _, bucket = aging_bucket(due, today)
    assert bucket == expected


def test_summarize_aging_skips_paid_invoices():
    today = date(2026, 6, 2)
    invs = [
        CustomerInvoice(1, "A", 1, "X", 100, 100, "posted", None, date(2026, 5, 1)),  # overdue
        CustomerInvoice(2, "B", 1, "X", 100, 0, "posted", None, date(2026, 5, 1)),    # paid -> skip
    ]
    summary = summarize_aging(invs, today)
    total = sum(b["amount"] for b in summary.values())
    assert total == 100


def test_bank_match_exact_amount_and_partner_is_high():
    today = date(2026, 6, 2)
    line = BankLine(1, today, 800.0, 7, "Initech", "ref", False)
    inv = CustomerInvoice(9, "INV", 7, "Initech", 800, 800, "posted", None, today)
    assert bank_match_score(line, inv, today, 3) == 0.95


def test_best_bank_match_picks_highest():
    today = date(2026, 6, 2)
    line = BankLine(1, today, 800.0, 7, "Initech", "ref", False)
    good = CustomerInvoice(9, "INV-G", 7, "Initech", 800, 800, "posted", None, today)
    wrong_partner = CustomerInvoice(8, "INV-W", 3, "Other", 800, 800, "posted", None, today)
    match = best_bank_match(line, [wrong_partner, good], today, 3)
    assert match.invoice_id == 9
    assert match.confidence == 0.95
