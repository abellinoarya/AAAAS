"""Accounts-payable tools: vendor bills, 3-way matching, expense coding."""
from __future__ import annotations

from ..logic import three_way_match
from ..odoo.models import PurchaseOrder, VendorBill
from .base import Tool, ToolContext, ToolResult, apply_policy, no_params

_VENDOR_BILL_FIELDS = [
    "id", "name", "partner_id", "ref", "amount_total", "state",
    "invoice_date", "invoice_date_due", "purchase_id",
]
_PO_FIELDS = ["id", "name", "partner_id", "amount_total", "state"]


def _load_bill(ctx: ToolContext, bill_id: int) -> VendorBill | None:
    rows = ctx.client.read("account.move", [bill_id], fields=_VENDOR_BILL_FIELDS)
    if not rows:
        return None
    line_rows = ctx.client.search_read(
        "account.move.line", [["move_id", "=", bill_id]],
        fields=["id", "product_id", "name", "quantity", "price_unit",
                "price_subtotal", "account_id", "analytic_account_id"],
    )
    return VendorBill.from_record(rows[0], line_rows)


def _load_po_by_ref(ctx: ToolContext, po_ref: str) -> PurchaseOrder | None:
    rows = ctx.client.search_read(
        "purchase.order", [["name", "=", po_ref]], fields=_PO_FIELDS, limit=1
    )
    if not rows:
        return None
    po = rows[0]
    line_rows = ctx.client.search_read(
        "purchase.order.line", [["order_id", "=", po["id"]]],
        fields=["id", "product_id", "name", "product_qty", "price_unit", "price_subtotal"],
    )
    return PurchaseOrder.from_record(po, line_rows)


def build_ap_tools(ctx: ToolContext) -> list[Tool]:
    def list_unmatched_vendor_bills() -> ToolResult:
        rows = ctx.client.search_read(
            "account.move",
            [["move_type", "=", "in_invoice"], ["purchase_id", "=", False],
             ["state", "=", "draft"]],
            fields=_VENDOR_BILL_FIELDS,
        )
        bills = [VendorBill.from_record(r) for r in rows]
        return ToolResult(
            ok=True,
            action="list_unmatched_vendor_bills",
            message=f"Found {len(bills)} unmatched draft vendor bill(s).",
            data={"bills": [
                {"id": b.id, "name": b.name, "vendor": b.vendor_name,
                 "amount_total": b.amount_total, "ref": b.ref}
                for b in bills
            ]},
        )

    def get_vendor_bill(bill_id: int) -> ToolResult:
        bill = _load_bill(ctx, bill_id)
        if bill is None:
            return ToolResult(False, "get_vendor_bill", f"No vendor bill {bill_id}.")
        return ToolResult(
            ok=True,
            action="get_vendor_bill",
            message=f"Vendor bill {bill.name} from {bill.vendor_name}, total {bill.amount_total:,.2f}.",
            data={"bill": {
                "id": bill.id, "name": bill.name, "vendor": bill.vendor_name,
                "vendor_id": bill.vendor_id, "ref": bill.ref,
                "amount_total": bill.amount_total, "state": bill.state,
                "purchase_id": bill.purchase_id,
                "due_date": bill.due_date.isoformat() if bill.due_date else None,
            }},
        )

    def get_purchase_order(po_ref: str) -> ToolResult:
        po = _load_po_by_ref(ctx, po_ref)
        if po is None:
            return ToolResult(False, "get_purchase_order", f"No purchase order {po_ref!r}.")
        return ToolResult(
            ok=True,
            action="get_purchase_order",
            message=f"PO {po.name} for {po.vendor_name}, total {po.amount_total:,.2f}.",
            data={"po": {
                "id": po.id, "name": po.name, "vendor": po.vendor_name,
                "amount_total": po.amount_total, "state": po.state,
            }},
        )

    def match_bill_to_po(bill_id: int, po_ref: str) -> ToolResult:
        bill = _load_bill(ctx, bill_id)
        if bill is None:
            return ToolResult(False, "match_bill_to_po", f"No vendor bill {bill_id}.")
        po = _load_po_by_ref(ctx, po_ref)
        if po is None:
            return ToolResult(False, "match_bill_to_po", f"No purchase order {po_ref!r}.")

        result = three_way_match(bill, po, ctx.settings.policy.price_variance_pct)

        def do_match() -> dict:
            ctx.client.write("account.move", bill.id, {"purchase_id": po.id})
            note = (
                f"<b>AAAAS</b> matched bill to PO {po.name}. {result.reason} "
                f"{ctx.personality.confidence_note(result.confidence)}"
            )
            ctx.client.log_note("account.move", bill.id, note)
            return {"matched_to": po.name, "variance_pct": round(result.variance_pct, 4)}

        summary = result.reason
        return apply_policy(
            ctx,
            action="match_bill_to_po",
            confidence=result.confidence,
            summary=summary,
            do_action=do_match,
            payload={"bill_id": bill.id, "po": po.name,
                     "variance_pct": round(result.variance_pct, 4),
                     "matched": result.matched},
            model="account.move",
            record_id=bill.id,
        )

    def code_expense_line(line_id: int, vendor_id: int, account_id: int, analytic: str = "") -> ToolResult:
        # Lean on learned patterns: if we've coded this vendor consistently
        # before, that raises confidence; a brand-new vendor stays cautious.
        suggestion, mem_conf = ctx.memory.suggest_coding(vendor_id)
        if suggestion and suggestion[0] == account_id:
            confidence = max(0.90, mem_conf)
        elif suggestion is None:
            confidence = 0.65  # no history -> draft for a human
        else:
            confidence = 0.55  # conflicts with learned pattern -> escalate

        def do_code() -> dict:
            vals = {"account_id": account_id}
            if analytic:
                vals["analytic_distribution"] = {analytic: 100}
            ctx.client.write("account.move.line", line_id, vals)
            ctx.memory.record_coding(vendor_id, account_id, analytic)
            ctx.client.log_note(
                "account.move.line", line_id,
                f"<b>AAAAS</b> coded line to account {account_id}"
                + (f" / analytic {analytic}" if analytic else ""),
            )
            return {"account_id": account_id, "analytic": analytic}

        return apply_policy(
            ctx,
            action="code_expense_line",
            confidence=confidence,
            summary=f"Code line {line_id} to account {account_id}"
                    + (f", analytic {analytic}" if analytic else ""),
            do_action=do_code,
            payload={"line_id": line_id, "account_id": account_id},
            model="account.move.line",
            record_id=line_id,
        )

    def validate_vendor_bill(bill_id: int) -> ToolResult:
        # HARD HITL: posting a bill is irreversible — always needs a human.
        bill = _load_bill(ctx, bill_id)
        if bill is None:
            return ToolResult(False, "validate_vendor_bill", f"No vendor bill {bill_id}.")

        def do_post() -> dict:
            ctx.client.write("account.move", bill.id, {"state": "posted"})
            ctx.client.log_note(
                "account.move", bill.id,
                "<b>AAAAS</b> posted this bill after human approval.",
            )
            return {"state": "posted"}

        return apply_policy(
            ctx,
            action="validate_vendor_bill",
            confidence=0.99,  # high competence, but policy forces a human anyway
            summary=f"Post vendor bill {bill.name} ({bill.vendor_name}, "
                    f"{bill.amount_total:,.2f}). This finalizes it in the ledger.",
            do_action=do_post,
            payload={"bill_id": bill.id, "amount_total": bill.amount_total},
            model="account.move",
            record_id=bill.id,
        )

    return [
        Tool("list_unmatched_vendor_bills",
             "List draft vendor bills not yet matched to a purchase order.",
             no_params(), lambda: list_unmatched_vendor_bills()),
        Tool("get_vendor_bill",
             "Read a single vendor bill by its Odoo id.",
             {"type": "object", "properties": {"bill_id": {"type": "integer"}},
              "required": ["bill_id"]},
             lambda bill_id: get_vendor_bill(bill_id)),
        Tool("get_purchase_order",
             "Read a purchase order by its reference/name (e.g. 'PO-2026-0089').",
             {"type": "object", "properties": {"po_ref": {"type": "string"}},
              "required": ["po_ref"]},
             lambda po_ref: get_purchase_order(po_ref)),
        Tool("match_bill_to_po",
             "Match a vendor bill to a purchase order via a 3-way check. Auto-matches "
             "within the price-variance tolerance; escalates to a human otherwise.",
             {"type": "object",
              "properties": {"bill_id": {"type": "integer"}, "po_ref": {"type": "string"}},
              "required": ["bill_id", "po_ref"]},
             lambda bill_id, po_ref: match_bill_to_po(bill_id, po_ref)),
        Tool("code_expense_line",
             "Assign an account (and optional analytic) to a bill line, using learned "
             "vendor patterns to gauge confidence.",
             {"type": "object",
              "properties": {"line_id": {"type": "integer"}, "vendor_id": {"type": "integer"},
                             "account_id": {"type": "integer"}, "analytic": {"type": "string"}},
              "required": ["line_id", "vendor_id", "account_id"]},
             lambda line_id, vendor_id, account_id, analytic="": code_expense_line(
                 line_id, vendor_id, account_id, analytic)),
        Tool("validate_vendor_bill",
             "Post (finalize) a vendor bill. ALWAYS requires human approval.",
             {"type": "object", "properties": {"bill_id": {"type": "integer"}},
              "required": ["bill_id"]},
             lambda bill_id: validate_vendor_bill(bill_id)),
    ]
