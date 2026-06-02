"""Pure, deterministic financial logic.

Everything here is a plain function of its inputs: no Odoo, no LLM, no
clock except what you pass in. This is deliberate — the money decisions
(3-way match, aging, bank reconciliation, confidence scoring) must be
exact and testable. The LLM orchestrates *which* of these to run and how
to talk to humans about the result; it never computes the numbers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .odoo.models import BankLine, CustomerInvoice, PurchaseOrder, VendorBill


# --------------------------------------------------------------------------- #
# Confidence from a relative variance
# --------------------------------------------------------------------------- #
def confidence_from_variance(variance_pct: float, threshold: float) -> float:
    """Map a relative variance to a confidence score in [0, 1].

    Exact matches are near-certain; confidence decays as variance grows past
    the policy threshold. Monotonic and deterministic.
    """
    v = abs(variance_pct)
    if v <= 0:
        return 0.99
    if v <= threshold * 0.34:
        return 0.95
    if v <= threshold:
        return 0.85
    if v <= threshold * 2:
        return 0.60
    if v <= threshold * 4:
        return 0.45
    return 0.30


# --------------------------------------------------------------------------- #
# 3-way match: vendor bill vs purchase order
# --------------------------------------------------------------------------- #
@dataclass
class MatchResult:
    matched: bool
    variance_pct: float
    confidence: float
    reason: str


def three_way_match(
    bill: VendorBill, po: PurchaseOrder, threshold: float
) -> MatchResult:
    """Compare a vendor bill to its purchase order by total value.

    A production system would also reconcile per-line quantities against
    goods receipts; for V1 we match on order total, which catches the bulk
    of real discrepancies (price creep, quantity drift, wrong PO).
    """
    if po.amount_total <= 0:
        return MatchResult(False, 1.0, 0.30, "Purchase order has no value to match against.")

    variance_pct = abs(bill.amount_total - po.amount_total) / po.amount_total
    confidence = confidence_from_variance(variance_pct, threshold)
    matched = variance_pct <= threshold

    direction = "over" if bill.amount_total > po.amount_total else "under"
    if matched:
        reason = (
            f"Bill {bill.amount_total:,.2f} matches PO {po.name} "
            f"({po.amount_total:,.2f}); variance {variance_pct:.2%} within "
            f"{threshold:.0%} tolerance."
        )
    else:
        reason = (
            f"Bill {bill.amount_total:,.2f} is {direction} PO {po.name} "
            f"({po.amount_total:,.2f}) by {variance_pct:.2%} — exceeds "
            f"{threshold:.0%} tolerance. Needs human review."
        )
    return MatchResult(matched, variance_pct, confidence, reason)


# --------------------------------------------------------------------------- #
# AR aging
# --------------------------------------------------------------------------- #
AGING_BUCKETS = ("current", "1-30", "31-60", "61-90", "90+")


def aging_bucket(due: date | None, today: date) -> tuple[int, str]:
    """Return (days_overdue, bucket). Negative days_overdue means not yet due."""
    if due is None:
        return 0, "current"
    days = (today - due).days
    if days <= 0:
        return days, "current"
    if days <= 30:
        return days, "1-30"
    if days <= 60:
        return days, "31-60"
    if days <= 90:
        return days, "61-90"
    return days, "90+"


def summarize_aging(invoices: list[CustomerInvoice], today: date) -> dict[str, dict]:
    """Bucketed totals for an AR aging report."""
    summary = {b: {"count": 0, "amount": 0.0} for b in AGING_BUCKETS}
    for inv in invoices:
        if not inv.is_open:
            continue
        _, bucket = aging_bucket(inv.due_date, today)
        summary[bucket]["count"] += 1
        summary[bucket]["amount"] += inv.amount_residual
    return summary


# --------------------------------------------------------------------------- #
# Bank reconciliation
# --------------------------------------------------------------------------- #
@dataclass
class BankMatch:
    invoice_id: int | None
    confidence: float
    reason: str


def bank_match_score(
    line: BankLine, invoice: CustomerInvoice, today: date, date_window_days: int
) -> float:
    """Confidence that a bank line settles a given customer invoice."""
    amount_close = abs(abs(line.amount) - invoice.amount_residual) <= 0.01
    amount_near = (
        invoice.amount_residual > 0
        and abs(abs(line.amount) - invoice.amount_residual) / invoice.amount_residual <= 0.01
    )
    partner_match = (
        line.partner_id is not None and line.partner_id == invoice.customer_id
    )

    if amount_close and partner_match:
        return 0.95
    if amount_close:
        return 0.78
    if amount_near and partner_match:
        return 0.70
    if partner_match:
        return 0.40
    return 0.20


def best_bank_match(
    line: BankLine,
    candidates: list[CustomerInvoice],
    today: date,
    date_window_days: int,
) -> BankMatch:
    """Pick the best-scoring open invoice for a bank line."""
    best: BankMatch = BankMatch(None, 0.0, "No candidate invoice scored above zero.")
    for inv in candidates:
        if not inv.is_open:
            continue
        score = bank_match_score(line, inv, today, date_window_days)
        if score > best.confidence:
            best = BankMatch(
                inv.id,
                score,
                f"Bank line {line.amount:,.2f} ({line.partner_name or 'unknown payer'}) "
                f"-> invoice {inv.name} residual {inv.amount_residual:,.2f}; "
                f"match confidence {score:.0%}.",
            )
    return best
