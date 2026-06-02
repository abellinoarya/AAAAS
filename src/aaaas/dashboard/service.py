"""Stdlib service layer behind the admin dashboard.

``DashboardHITL`` is a human-in-the-loop channel that *defers* prepared actions
into an approval queue instead of acting synchronously — the realistic pattern
(the agent prepares, a human approves later). ``DashboardService`` drives tools,
records every action as ``Activity``, exposes the pending queue, and computes
the ROI metrics the dashboard sells on (transactions processed, hours saved).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from ..agent.confidence import Decision
from ..hitl.interface import HITLChannel, HITLDecision, HITLRequest, HITLStatus
from ..tools.base import ToolResult

# Rough, defensible estimate of human time saved per auto-processed transaction.
MINUTES_SAVED_PER_TXN = 5.0


@dataclass
class PendingApproval:
    id: int
    req: HITLRequest
    callback: Callable[[], dict | None]

    def serialize(self) -> dict:
        return {
            "id": self.id,
            "action": self.req.action,
            "summary": self.req.summary,
            "confidence": round(self.req.confidence, 3),
            "model": self.req.model,
            "record_id": self.req.record_id,
            "payload": self.req.payload,
        }


class DashboardHITL(HITLChannel):
    """Queues prepared actions for asynchronous human approval."""

    def __init__(self) -> None:
        self._pending: dict[int, PendingApproval] = {}
        self._seq = 0
        self.resolved: list[dict] = []

    # apply_policy calls request() first (we say "not now, queue it"), then
    # defer() with the prepared action.
    def request(self, req: HITLRequest) -> HITLDecision:
        return HITLDecision(HITLStatus.EXPIRED, note="queued for human approval")

    def defer(self, req: HITLRequest, callback: Callable[[], dict | None]) -> int:
        self._seq += 1
        self._pending[self._seq] = PendingApproval(self._seq, req, callback)
        return self._seq

    def pending(self) -> list[PendingApproval]:
        return list(self._pending.values())

    def approve(self, pid: int) -> dict:
        pa = self._pending.pop(pid)
        result = pa.callback() or {}
        self.resolved.append(
            {"id": pid, "action": pa.req.action, "status": "approved", "result": result})
        return result

    def reject(self, pid: int, note: str = "") -> None:
        pa = self._pending.pop(pid)
        self.resolved.append(
            {"id": pid, "action": pa.req.action, "status": "rejected", "note": note})


@dataclass
class Activity:
    ts: str
    tool: str
    ok: bool
    decision: str | None
    confidence: float
    message: str

    def serialize(self) -> dict:
        return {
            "ts": self.ts, "tool": self.tool, "ok": self.ok,
            "decision": self.decision, "confidence": round(self.confidence, 3),
            "message": self.message,
        }


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


@dataclass
class DashboardService:
    """Aggregates everything the dashboard renders."""

    bookkeeper: Any  # aaaas.app.Bookkeeper (avoids an import cycle)
    activity: list[Activity] = field(default_factory=list)
    demo_ids: dict[str, int] = field(default_factory=dict)

    @property
    def hitl(self) -> DashboardHITL:
        return self.bookkeeper.context.hitl

    # ---- driving tools ---- #
    def call_tool(self, name: str, **kwargs) -> ToolResult:
        tool = self.bookkeeper.registry.get(name)
        if tool is None:
            raise KeyError(f"Unknown tool {name!r}")
        result = tool.func(**kwargs)
        self._record(result)
        return result

    def _record(self, result: ToolResult) -> None:
        self.activity.append(Activity(
            ts=_now(), tool=result.action, ok=result.ok,
            decision=result.decision.value if result.decision else None,
            confidence=result.confidence, message=result.message,
        ))

    def run_demo_batch(self) -> None:
        """Drive a representative set of actions to populate the dashboard.

        Uses the seeded ids; the over-tolerance match and the bill posting land
        in the approval queue, the clean match and exact reconcile auto-process.
        """
        ids = self.demo_ids
        if not ids:
            return
        self.call_tool("match_bill_to_po", bill_id=ids["bill_clean"], po_ref="PO-2026-0089")
        self.call_tool("match_bill_to_po", bill_id=ids["bill_variance"], po_ref="PO-2026-0090")
        self.call_tool("reconcile_bank_line", bank_line_id=ids["bank_match"])
        self.call_tool("reconcile_bank_line", bank_line_id=ids["bank_orphan"])
        self.call_tool("validate_vendor_bill", bill_id=ids["bill_clean"])
        self.call_tool("generate_ar_aging_report")

    # ---- approvals ---- #
    def approvals(self) -> list[dict]:
        return [pa.serialize() for pa in self.hitl.pending()]

    def approve(self, pid: int) -> dict:
        result = self.hitl.approve(pid)
        self.activity.append(Activity(
            ts=_now(), tool="approval", ok=True, decision="approved",
            confidence=1.0, message=f"Human approved request #{pid}: {result}"))
        return result

    def reject(self, pid: int, note: str = "") -> None:
        self.hitl.reject(pid, note)
        self.activity.append(Activity(
            ts=_now(), tool="approval", ok=False, decision="rejected",
            confidence=1.0, message=f"Human rejected request #{pid}. {note}".strip()))

    # ---- metrics / views ---- #
    def metrics(self) -> dict:
        auto = sum(1 for a in self.activity
                   if a.ok and a.decision in (Decision.AUTO.value, Decision.AUTO_FLAG.value))
        flagged = sum(1 for a in self.activity if a.decision == Decision.AUTO_FLAG.value)
        paused = sum(1 for a in self.activity if a.decision == Decision.PAUSE.value)
        pending = len(self.hitl.pending())
        approved = sum(1 for r in self.hitl.resolved if r["status"] == "approved")
        minutes = (auto + approved) * MINUTES_SAVED_PER_TXN
        return {
            "transactions_processed": auto + approved,
            "auto_processed": auto,
            "flagged_for_review": flagged,
            "paused": paused,
            "pending_approval": pending,
            "human_approved": approved,
            "hours_saved": round(minutes / 60.0, 1),
            "automation_rate": round(auto / max(1, auto + pending + paused), 3),
        }

    def recent_activity(self, limit: int = 25) -> list[dict]:
        return [a.serialize() for a in reversed(self.activity[-limit:])]

    def notices(self) -> list[str]:
        return list(self.bookkeeper.context.notices)
