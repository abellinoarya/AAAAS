"""Bank reconciliation tools."""
from __future__ import annotations

from ..logic import best_bank_match
from ..odoo.models import BankLine, CustomerInvoice
from .base import Tool, ToolContext, ToolResult, apply_policy, no_params

_INVOICE_FIELDS = [
    "id", "name", "partner_id", "amount_total", "amount_residual",
    "state", "invoice_date", "invoice_date_due",
]
_BANK_FIELDS = ["id", "date", "amount", "partner_id", "payment_ref", "is_reconciled"]


def build_bank_tools(ctx: ToolContext) -> list[Tool]:
    def list_unreconciled_bank_lines() -> ToolResult:
        rows = ctx.client.search_read(
            "account.bank.statement.line",
            [["is_reconciled", "=", False]], fields=_BANK_FIELDS,
        )
        lines = [BankLine.from_record(r) for r in rows]
        return ToolResult(
            ok=True,
            action="list_unreconciled_bank_lines",
            message=f"{len(lines)} unreconciled bank line(s).",
            data={"lines": [
                {"id": l.id, "amount": l.amount, "partner": l.partner_name,
                 "ref": l.payment_ref, "date": l.date.isoformat() if l.date else None}
                for l in lines
            ]},
        )

    def reconcile_bank_line(bank_line_id: int) -> ToolResult:
        rows = ctx.client.read(
            "account.bank.statement.line", [bank_line_id], fields=_BANK_FIELDS)
        if not rows:
            return ToolResult(False, "reconcile_bank_line", f"No bank line {bank_line_id}.")
        line = BankLine.from_record(rows[0])

        inv_rows = ctx.client.search_read(
            "account.move",
            [["move_type", "=", "out_invoice"], ["state", "=", "posted"]],
            fields=_INVOICE_FIELDS,
        )
        candidates = [CustomerInvoice.from_record(r) for r in inv_rows]
        match = best_bank_match(
            line, candidates, ctx.today, ctx.settings.policy.bank_match_date_window_days)

        if match.invoice_id is None:
            ctx.notices.append(f"[UNMATCHED] Bank line {line.id} ({line.amount:,.2f}) — no candidate.")
            return ToolResult(
                ok=False, action="reconcile_bank_line",
                message=f"No invoice matches bank line {line.id} ({line.amount:,.2f}).",
                confidence=match.confidence, data={"bank_line_id": line.id},
            )

        def do_reconcile() -> dict:
            ctx.client.write(
                "account.bank.statement.line", line.id, {"is_reconciled": True})
            inv_rows2 = ctx.client.read(
                "account.move", [match.invoice_id], fields=["amount_residual"])
            residual = inv_rows2[0]["amount_residual"] if inv_rows2 else 0
            new_residual = max(0.0, float(residual) - abs(line.amount))
            ctx.client.write("account.move", match.invoice_id, {"amount_residual": new_residual})
            ctx.client.log_note(
                "account.move", match.invoice_id,
                f"<b>AAAAS</b> reconciled bank line {line.id} ({line.amount:,.2f}). {match.reason}",
            )
            return {"reconciled_with_invoice": match.invoice_id, "new_residual": new_residual}

        return apply_policy(
            ctx,
            action="reconcile_bank_line",
            confidence=match.confidence,
            summary=match.reason,
            do_action=do_reconcile,
            payload={"bank_line_id": line.id, "invoice_id": match.invoice_id},
            model="account.bank.statement.line",
            record_id=line.id,
        )

    return [
        Tool("list_unreconciled_bank_lines",
             "List bank statement lines that are not yet reconciled.",
             no_params(), lambda: list_unreconciled_bank_lines()),
        Tool("reconcile_bank_line",
             "Find the best-matching open invoice for a bank line and reconcile it. "
             "Auto for exact matches; escalates fuzzy ones.",
             {"type": "object", "properties": {"bank_line_id": {"type": "integer"}},
              "required": ["bank_line_id"]},
             lambda bank_line_id: reconcile_bank_line(bank_line_id)),
    ]
