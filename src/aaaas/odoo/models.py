"""Typed views over the Odoo records the bookkeeping agent works with.

These are thin dataclasses built from raw Odoo dicts via ``from_record``.
They exist so tools and logic operate on real attributes instead of
stringly-typed dicts — and so a version change in Odoo is absorbed here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


def _to_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _m2o_id(value: Any) -> int | None:
    """Odoo many2one fields read as ``[id, "Display Name"]`` or ``False``."""
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])
    if isinstance(value, int):
        return value
    return None


def _m2o_name(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) > 1:
        return str(value[1])
    return ""


@dataclass
class LineItem:
    """A line on a bill or purchase order."""

    id: int | None
    product: str
    quantity: float
    price_unit: float
    price_subtotal: float
    account_id: int | None = None
    analytic: str = ""

    @classmethod
    def from_record(cls, rec: dict) -> "LineItem":
        return cls(
            id=rec.get("id"),
            product=_m2o_name(rec.get("product_id")) or rec.get("name", ""),
            quantity=float(rec.get("quantity", rec.get("product_qty", 0)) or 0),
            price_unit=float(rec.get("price_unit", 0) or 0),
            price_subtotal=float(rec.get("price_subtotal", 0) or 0),
            account_id=_m2o_id(rec.get("account_id")),
            analytic=_m2o_name(rec.get("analytic_account_id")),
        )


@dataclass
class VendorBill:
    """``account.move`` with ``move_type='in_invoice'``."""

    id: int
    name: str
    vendor_id: int | None
    vendor_name: str
    ref: str
    amount_total: float
    state: str               # draft | posted | cancel
    invoice_date: date | None
    due_date: date | None
    purchase_id: int | None  # linked PO, if matched
    lines: list[LineItem] = field(default_factory=list)

    @classmethod
    def from_record(cls, rec: dict, lines: list[dict] | None = None) -> "VendorBill":
        return cls(
            id=int(rec["id"]),
            name=rec.get("name") or "",
            vendor_id=_m2o_id(rec.get("partner_id")),
            vendor_name=_m2o_name(rec.get("partner_id")),
            ref=rec.get("ref") or "",
            amount_total=float(rec.get("amount_total", 0) or 0),
            state=rec.get("state") or "draft",
            invoice_date=_to_date(rec.get("invoice_date")),
            due_date=_to_date(rec.get("invoice_date_due")),
            purchase_id=_m2o_id(rec.get("purchase_id")),
            lines=[LineItem.from_record(l) for l in (lines or [])],
        )


@dataclass
class PurchaseOrder:
    """``purchase.order``."""

    id: int
    name: str
    vendor_id: int | None
    vendor_name: str
    amount_total: float
    state: str
    lines: list[LineItem] = field(default_factory=list)

    @classmethod
    def from_record(cls, rec: dict, lines: list[dict] | None = None) -> "PurchaseOrder":
        return cls(
            id=int(rec["id"]),
            name=rec.get("name") or "",
            vendor_id=_m2o_id(rec.get("partner_id")),
            vendor_name=_m2o_name(rec.get("partner_id")),
            amount_total=float(rec.get("amount_total", 0) or 0),
            state=rec.get("state") or "draft",
            lines=[LineItem.from_record(l) for l in (lines or [])],
        )


@dataclass
class CustomerInvoice:
    """``account.move`` with ``move_type='out_invoice'``."""

    id: int
    name: str
    customer_id: int | None
    customer_name: str
    amount_total: float
    amount_residual: float    # outstanding balance
    state: str
    invoice_date: date | None
    due_date: date | None

    @classmethod
    def from_record(cls, rec: dict) -> "CustomerInvoice":
        return cls(
            id=int(rec["id"]),
            name=rec.get("name") or "",
            customer_id=_m2o_id(rec.get("partner_id")),
            customer_name=_m2o_name(rec.get("partner_id")),
            amount_total=float(rec.get("amount_total", 0) or 0),
            amount_residual=float(rec.get("amount_residual", 0) or 0),
            state=rec.get("state") or "draft",
            invoice_date=_to_date(rec.get("invoice_date")),
            due_date=_to_date(rec.get("invoice_date_due")),
        )

    @property
    def is_open(self) -> bool:
        return self.state == "posted" and self.amount_residual > 0.005


@dataclass
class BankLine:
    """``account.bank.statement.line``."""

    id: int
    date: date | None
    amount: float
    partner_id: int | None
    partner_name: str
    payment_ref: str
    reconciled: bool

    @classmethod
    def from_record(cls, rec: dict) -> "BankLine":
        return cls(
            id=int(rec["id"]),
            date=_to_date(rec.get("date")),
            amount=float(rec.get("amount", 0) or 0),
            partner_id=_m2o_id(rec.get("partner_id")),
            partner_name=_m2o_name(rec.get("partner_id")),
            payment_ref=rec.get("payment_ref") or rec.get("ref") or "",
            reconciled=bool(rec.get("is_reconciled", rec.get("reconciled", False))),
        )
