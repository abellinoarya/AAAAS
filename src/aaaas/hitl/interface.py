"""Human-in-the-loop: how the agent asks a person to approve an action.

A ``HITLChannel`` takes a structured ``HITLRequest`` and returns a
``HITLDecision``. The same interface backs every delivery mechanism:

  * ``AutoApproveHITL`` / ``AutoRejectHITL`` — deterministic, for tests/demos
  * ``QueueHITL``     — enqueues requests for an async approver (web/Slack)
  * ``ConsoleHITL``   — prompts a human at the terminal

In production this is where Slack/email/web approvals plug in. The agent and
tools depend only on the abstract channel, never on a transport.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class HITLStatus(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"
    EXPIRED = "expired"


@dataclass
class HITLRequest:
    action: str                       # e.g. "validate_vendor_bill"
    summary: str                      # human-readable "what & why"
    confidence: float
    payload: dict[str, Any] = field(default_factory=dict)
    model: str | None = None          # Odoo model the action touches
    record_id: int | None = None


@dataclass
class HITLDecision:
    status: HITLStatus
    note: str = ""
    modified_payload: dict[str, Any] | None = None

    @property
    def approved(self) -> bool:
        return self.status in (HITLStatus.APPROVED, HITLStatus.MODIFIED)


class HITLChannel:
    """Base channel. Subclasses implement ``request``."""

    def request(self, req: HITLRequest) -> HITLDecision:  # pragma: no cover - abstract
        raise NotImplementedError


class AutoApproveHITL(HITLChannel):
    """Approves everything. For demos and happy-path tests only."""

    def __init__(self) -> None:
        self.seen: list[HITLRequest] = []

    def request(self, req: HITLRequest) -> HITLDecision:
        self.seen.append(req)
        return HITLDecision(HITLStatus.APPROVED, note="auto-approved (demo channel)")


class AutoRejectHITL(HITLChannel):
    """Rejects everything. For testing the blocked path."""

    def __init__(self) -> None:
        self.seen: list[HITLRequest] = []

    def request(self, req: HITLRequest) -> HITLDecision:
        self.seen.append(req)
        return HITLDecision(HITLStatus.REJECTED, note="auto-rejected (test channel)")


class QueueHITL(HITLChannel):
    """Collects requests for an out-of-band approver.

    ``request`` returns EXPIRED immediately (nothing acts without a human);
    a real approver later resolves items via ``resolve``. This models the
    async reality: the agent prepares, a person decides on their own time.
    """

    def __init__(self) -> None:
        self.pending: list[HITLRequest] = []
        self.resolved: list[tuple[HITLRequest, HITLDecision]] = []

    def request(self, req: HITLRequest) -> HITLDecision:
        self.pending.append(req)
        return HITLDecision(HITLStatus.EXPIRED, note="queued for human approval")

    def resolve(self, index: int, decision: HITLDecision) -> None:
        req = self.pending.pop(index)
        self.resolved.append((req, decision))


class ConsoleHITL(HITLChannel):
    """Prompts a human at the terminal. ``input_fn`` is injectable for tests."""

    def __init__(self, input_fn: Callable[[str], str] = input, output_fn: Callable[[str], None] = print):
        self._input = input_fn
        self._output = output_fn

    def request(self, req: HITLRequest) -> HITLDecision:
        self._output("\n" + "=" * 60)
        self._output(f"APPROVAL NEEDED — {req.action}")
        self._output(f"Confidence: {req.confidence:.0%}")
        self._output(req.summary)
        if req.payload:
            self._output(f"Details: {req.payload}")
        self._output("=" * 60)
        answer = self._input("Approve? [y/N]: ").strip().lower()
        if answer in {"y", "yes"}:
            return HITLDecision(HITLStatus.APPROVED, note="approved at console")
        return HITLDecision(HITLStatus.REJECTED, note="rejected at console")
