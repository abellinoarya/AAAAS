"""Tool framework: the agent-callable surface over Odoo.

A ``Tool`` is a named, schema-described function the LLM can call (the schema
maps directly to Anthropic's tool-use format). ``ToolContext`` bundles the
dependencies every tool needs. ``apply_policy`` is the single chokepoint that
enforces the confidence gates and hard human-in-the-loop rules — every tool
that *writes* routes its write through it, so the escalation policy can't be
bypassed by an individual tool.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from ..agent.confidence import Decision, decide, is_hard_hitl
from ..agent.personality import Personality
from ..config import Settings
from ..hitl.interface import HITLChannel, HITLRequest, HITLStatus
from ..memory.store import PatternMemory
from ..odoo.client import OdooClient


@dataclass
class ToolContext:
    """Everything a tool needs to do its job."""

    client: OdooClient
    settings: Settings
    hitl: HITLChannel
    personality: Personality
    memory: PatternMemory
    today: date
    # Side-channel where tools drop items for the daily human summary.
    notices: list[str] = field(default_factory=list)


@dataclass
class ToolResult:
    ok: bool
    action: str
    message: str
    confidence: float = 1.0
    decision: Decision | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """The structured view handed back to the LLM after a tool call."""
        return {
            "ok": self.ok,
            "action": self.action,
            "message": self.message,
            "confidence": round(self.confidence, 3),
            "decision": self.decision.value if self.decision else None,
            **self.data,
        }


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable[..., ToolResult]

    @property
    def requires_hitl(self) -> bool:
        return is_hard_hitl(self.name)

    def to_anthropic_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def extend(self, tools: list[Tool]) -> None:
        for t in tools:
            self.register(t)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def to_anthropic_schemas(self) -> list[dict]:
        return [t.to_anthropic_schema() for t in self._tools.values()]


def no_params() -> dict:
    return {"type": "object", "properties": {}, "additionalProperties": False}


def apply_policy(
    ctx: ToolContext,
    action: str,
    confidence: float,
    summary: str,
    do_action: Callable[[], dict | None],
    *,
    payload: dict | None = None,
    model: str | None = None,
    record_id: int | None = None,
) -> ToolResult:
    """Run ``do_action`` only if the policy allows it; otherwise escalate.

    This is the legal firewall in code form. Hard-HITL actions and anything in
    the draft band go to a human first; low confidence pauses; only the auto
    bands execute immediately.
    """
    payload = payload or {}
    thresholds = ctx.settings.confidence
    decision = decide(confidence, thresholds)
    hard = is_hard_hitl(action)

    # --- route to a human: hard rules, or the draft-and-escalate band --- #
    if hard or decision == Decision.DRAFT_HITL:
        req = HITLRequest(
            action=action,
            summary=summary,
            confidence=confidence,
            payload=payload,
            model=model,
            record_id=record_id,
        )
        verdict = ctx.hitl.request(req)
        if verdict.approved:
            extra = do_action() or {}
            return ToolResult(
                ok=True,
                action=action,
                message=f"Human-approved. {summary}",
                confidence=confidence,
                decision=decision,
                data={"hitl": verdict.status.value, **payload, **extra},
            )
        # Async approval: if the channel can defer (e.g. a dashboard/Slack
        # queue), hand it the prepared action to run on later approval. The
        # action does NOT execute now — it waits for a human.
        if verdict.status == HITLStatus.EXPIRED and hasattr(ctx.hitl, "defer"):
            ctx.hitl.defer(req, do_action)
            ctx.notices.append(f"[PENDING APPROVAL] {action}: {summary}")
            return ToolResult(
                ok=False,
                action=action,
                message=f"Queued for human approval. {summary}",
                confidence=confidence,
                decision=decision,
                data={"hitl": "pending", **payload},
            )
        ctx.notices.append(f"[AWAITING HUMAN] {action}: {summary}")
        return ToolResult(
            ok=False,
            action=action,
            message=f"Routed to a human ({verdict.status.value}); not executed. {summary}",
            confidence=confidence,
            decision=decision,
            data={"hitl": verdict.status.value, **payload},
        )

    # --- confidence too low: pause and notify, do not act --- #
    if decision == Decision.PAUSE:
        ctx.notices.append(f"[PAUSED] {action}: {summary}")
        return ToolResult(
            ok=False,
            action=action,
            message=f"Paused — confidence {confidence:.0%} below threshold. {summary}",
            confidence=confidence,
            decision=decision,
            data=payload,
        )

    # --- auto bands: execute now (flag for review in the soft band) --- #
    extra = do_action() or {}
    if decision == Decision.AUTO_FLAG:
        ctx.notices.append(f"[REVIEW] {action}: {summary}")
    return ToolResult(
        ok=True,
        action=action,
        message=summary,
        confidence=confidence,
        decision=decision,
        data={**payload, **extra},
    )
