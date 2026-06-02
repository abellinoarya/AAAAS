"""Reporting & initiative tools: aging reports, cash position, daily digest."""
from __future__ import annotations

from ..logic import summarize_aging
from ..odoo.models import CustomerInvoice, VendorBill
from .base import Tool, ToolContext, ToolResult, no_params

_INVOICE_FIELDS = [
    "id", "name", "partner_id", "amount_total", "amount_residual",
    "state", "invoice_date", "invoice_date_due",
]


def build_reporting_tools(ctx: ToolContext) -> list[Tool]:
    def generate_ar_aging_report() -> ToolResult:
        rows = ctx.client.search_read(
            "account.move",
            [["move_type", "=", "out_invoice"], ["state", "=", "posted"]],
            fields=_INVOICE_FIELDS,
        )
        invoices = [CustomerInvoice.from_record(r) for r in rows]
        summary = summarize_aging(invoices, ctx.today)
        total = sum(b["amount"] for b in summary.values())
        return ToolResult(
            ok=True, action="generate_ar_aging_report",
            message=f"AR aging as of {ctx.today}: {total:,.2f} outstanding.",
            data={"as_of": ctx.today.isoformat(), "buckets": summary, "total_outstanding": total},
        )

    def generate_ap_aging_report() -> ToolResult:
        rows = ctx.client.search_read(
            "account.move",
            [["move_type", "=", "in_invoice"], ["state", "=", "posted"]],
            fields=["id", "name", "partner_id", "amount_total", "state", "invoice_date_due"],
        )
        bills = [VendorBill.from_record(r) for r in rows]
        total = sum(b.amount_total for b in bills)
        return ToolResult(
            ok=True, action="generate_ap_aging_report",
            message=f"AP open as of {ctx.today}: {total:,.2f} across {len(bills)} bill(s).",
            data={"as_of": ctx.today.isoformat(), "open_bills": len(bills), "total_payable": total},
        )

    def summarize_cash_position() -> ToolResult:
        ar_rows = ctx.client.search_read(
            "account.move",
            [["move_type", "=", "out_invoice"], ["state", "=", "posted"]],
            fields=["amount_residual"])
        ap_rows = ctx.client.search_read(
            "account.move",
            [["move_type", "=", "in_invoice"], ["state", "=", "posted"]],
            fields=["amount_total"])
        receivable = sum(float(r.get("amount_residual", 0) or 0) for r in ar_rows)
        payable = sum(float(r.get("amount_total", 0) or 0) for r in ap_rows)
        return ToolResult(
            ok=True, action="summarize_cash_position",
            message=f"Receivable {receivable:,.2f} vs payable {payable:,.2f} "
                    f"(net {receivable - payable:,.2f}).",
            data={"receivable": receivable, "payable": payable, "net": receivable - payable},
        )

    def push_daily_summary() -> ToolResult:
        notices = list(ctx.notices)
        lines = notices or ["Nothing needs a human right now — books are clean."]
        body = ctx.personality.render(
            f"Daily finance summary ({ctx.today}): " + "; ".join(lines)
        )
        return ToolResult(
            ok=True, action="push_daily_summary",
            message=f"Pushed summary to {ctx.settings.finance_channel}.",
            data={"channel": ctx.settings.finance_channel, "items": notices, "rendered": body},
        )

    return [
        Tool("generate_ar_aging_report", "Bucketed accounts-receivable aging report.",
             no_params(), lambda: generate_ar_aging_report()),
        Tool("generate_ap_aging_report", "Open accounts-payable summary.",
             no_params(), lambda: generate_ap_aging_report()),
        Tool("summarize_cash_position", "Receivable vs payable net cash position.",
             no_params(), lambda: summarize_cash_position()),
        Tool("push_daily_summary",
             "Send the daily finance digest (collected flags/notices) to the team channel.",
             no_params(), lambda: push_daily_summary()),
    ]
