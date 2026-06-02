"""Journal entry tools: recurring drafts and the hard-gated posting step."""
from __future__ import annotations

from .base import Tool, ToolContext, ToolResult, apply_policy, no_params


def build_journal_tools(ctx: ToolContext) -> list[Tool]:
    def list_recurring_entries() -> ToolResult:
        rows = ctx.client.search_read(
            "account.move",
            [["move_type", "=", "entry"], ["aaaas_recurring", "=", True]],
            fields=["id", "name", "ref", "amount_total", "state"],
        )
        return ToolResult(
            ok=True, action="list_recurring_entries",
            message=f"{len(rows)} recurring entry template(s).",
            data={"templates": rows},
        )

    def draft_recurring_entry(template_id: int, period: str) -> ToolResult:
        rows = ctx.client.read(
            "account.move", [template_id], fields=["id", "name", "ref", "amount_total"])
        if not rows:
            return ToolResult(False, "draft_recurring_entry", f"No template {template_id}.")
        tmpl = rows[0]

        def do_draft() -> dict:
            new_id = ctx.client.create("account.move", {
                "move_type": "entry",
                "name": False,
                "ref": f"{tmpl.get('ref') or tmpl.get('name')} — {period}",
                "amount_total": tmpl.get("amount_total", 0),
                "state": "draft",
                "aaaas_recurring": False,
            })
            ctx.client.log_note(
                "account.move", new_id,
                f"<b>AAAAS</b> drafted recurring entry for {period} from template "
                f"{tmpl.get('name')}. Awaiting human posting.",
            )
            return {"draft_entry_id": new_id}

        # Drafting is safe (nothing posted); high confidence, acts automatically.
        return apply_policy(
            ctx,
            action="draft_recurring_entry",
            confidence=0.93,
            summary=f"Draft recurring entry for {period} from template {tmpl.get('name')}.",
            do_action=do_draft,
            payload={"template_id": template_id, "period": period},
            model="account.move",
            record_id=template_id,
        )

    def post_journal_entry(entry_id: int) -> ToolResult:
        # HARD HITL: finalizing an entry is irreversible — always a human.
        rows = ctx.client.read("account.move", [entry_id], fields=["id", "name", "ref", "amount_total"])
        if not rows:
            return ToolResult(False, "post_journal_entry", f"No entry {entry_id}.")
        entry = rows[0]

        def do_post() -> dict:
            ctx.client.write("account.move", entry_id, {"state": "posted"})
            ctx.client.log_note(
                "account.move", entry_id,
                "<b>AAAAS</b> posted this journal entry after human approval.")
            return {"state": "posted"}

        return apply_policy(
            ctx,
            action="post_journal_entry",
            confidence=0.99,
            summary=f"Post journal entry {entry.get('ref') or entry.get('name')} "
                    f"({entry.get('amount_total', 0):,.2f}). Finalizes it in the ledger.",
            do_action=do_post,
            payload={"entry_id": entry_id},
            model="account.move",
            record_id=entry_id,
        )

    return [
        Tool("list_recurring_entries",
             "List recurring/accrual journal entry templates.",
             no_params(), lambda: list_recurring_entries()),
        Tool("draft_recurring_entry",
             "Create a draft journal entry from a recurring template for a period.",
             {"type": "object",
              "properties": {"template_id": {"type": "integer"}, "period": {"type": "string"}},
              "required": ["template_id", "period"]},
             lambda template_id, period: draft_recurring_entry(template_id, period)),
        Tool("post_journal_entry",
             "Post (finalize) a journal entry. ALWAYS requires human approval.",
             {"type": "object", "properties": {"entry_id": {"type": "integer"}},
              "required": ["entry_id"]},
             lambda entry_id: post_journal_entry(entry_id)),
    ]
