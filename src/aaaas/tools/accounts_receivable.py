"""Accounts-receivable tools: overdue invoices, reminders, collections."""
from __future__ import annotations

from ..logic import aging_bucket
from ..odoo.models import CustomerInvoice
from .base import Tool, ToolContext, ToolResult, apply_policy, no_params

_INVOICE_FIELDS = [
    "id", "name", "partner_id", "amount_total", "amount_residual",
    "state", "invoice_date", "invoice_date_due",
]


def _open_invoices(ctx: ToolContext) -> list[CustomerInvoice]:
    rows = ctx.client.search_read(
        "account.move",
        [["move_type", "=", "out_invoice"], ["state", "=", "posted"]],
        fields=_INVOICE_FIELDS,
    )
    return [i for i in (CustomerInvoice.from_record(r) for r in rows) if i.is_open]


def build_ar_tools(ctx: ToolContext) -> list[Tool]:
    def list_overdue_invoices() -> ToolResult:
        overdue = []
        for inv in _open_invoices(ctx):
            days, bucket = aging_bucket(inv.due_date, ctx.today)
            if days > 0:
                overdue.append({
                    "id": inv.id, "name": inv.name, "customer": inv.customer_name,
                    "residual": inv.amount_residual, "days_overdue": days, "bucket": bucket,
                })
        overdue.sort(key=lambda x: x["days_overdue"], reverse=True)
        return ToolResult(
            ok=True,
            action="list_overdue_invoices",
            message=f"{len(overdue)} overdue invoice(s).",
            data={"overdue": overdue},
        )

    def send_payment_reminder(invoice_id: int) -> ToolResult:
        rows = ctx.client.read("account.move", [invoice_id], fields=_INVOICE_FIELDS)
        if not rows:
            return ToolResult(False, "send_payment_reminder", f"No invoice {invoice_id}.")
        inv = CustomerInvoice.from_record(rows[0])
        days, _ = aging_bucket(inv.due_date, ctx.today)

        # Gentle, recent reminders go automatically; older debt is a judgment
        # call and an external relationship — that always gets a human.
        within_auto = 0 < days <= ctx.settings.policy.reminder_auto_max_days
        confidence = 0.92 if within_auto else 0.55

        def do_send() -> dict:
            # external_facing=True -> never apply playful tone to a customer.
            body = ctx.personality.render(
                f"Friendly reminder: invoice {inv.name} for "
                f"{inv.amount_residual:,.2f} was due {inv.due_date}. "
                f"Please arrange payment at your earliest convenience.",
                external_facing=True,
            )
            ctx.client.log_note("account.move", inv.id, f"<b>AAAAS</b> sent reminder: {body}")
            return {"days_overdue": days, "reminder_sent": True}

        return apply_policy(
            ctx,
            action="send_payment_reminder",
            confidence=confidence,
            summary=f"Send payment reminder for {inv.name} ({inv.customer_name}, "
                    f"{days} days overdue, {inv.amount_residual:,.2f}).",
            do_action=do_send,
            payload={"invoice_id": inv.id, "days_overdue": days},
            model="account.move",
            record_id=inv.id,
        )

    def escalate_collection(invoice_id: int, note: str = "") -> ToolResult:
        rows = ctx.client.read("account.move", [invoice_id], fields=_INVOICE_FIELDS)
        if not rows:
            return ToolResult(False, "escalate_collection", f"No invoice {invoice_id}.")
        inv = CustomerInvoice.from_record(rows[0])

        def do_escalate() -> dict:
            ctx.client.log_note(
                "account.move", inv.id,
                f"<b>AAAAS</b> flagged for collections. {note}".strip(),
            )
            return {"escalated": True}

        return apply_policy(
            ctx,
            action="escalate_collection",
            confidence=0.95,
            summary=f"Escalate {inv.name} ({inv.customer_name}, {inv.amount_residual:,.2f}) "
                    f"to collections.",
            do_action=do_escalate,
            payload={"invoice_id": inv.id},
            model="account.move",
            record_id=inv.id,
        )

    return [
        Tool("list_overdue_invoices",
             "List posted customer invoices that are past their due date.",
             no_params(), lambda: list_overdue_invoices()),
        Tool("send_payment_reminder",
             "Send a payment reminder for an overdue invoice. Auto for recent overdue; "
             "older debt requires human approval.",
             {"type": "object", "properties": {"invoice_id": {"type": "integer"}},
              "required": ["invoice_id"]},
             lambda invoice_id: send_payment_reminder(invoice_id)),
        Tool("escalate_collection",
             "Flag an invoice for the collections process. Requires human approval.",
             {"type": "object",
              "properties": {"invoice_id": {"type": "integer"}, "note": {"type": "string"}},
              "required": ["invoice_id"]},
             lambda invoice_id, note="": escalate_collection(invoice_id, note)),
    ]
