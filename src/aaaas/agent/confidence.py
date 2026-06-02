"""Confidence-gated escalation policy (architecture doc §6).

    confidence >= auto       -> AUTO       act autonomously, log to chatter
    confidence >= auto_flag  -> AUTO_FLAG  act, but flag in the daily summary
    confidence >= draft_hitl -> DRAFT_HITL draft the action, escalate, wait
    confidence <  draft_hitl -> PAUSE      stop, log a blocker, notify a human

On top of the gradient sit HARD rules: some actions ALWAYS require a human,
no matter how confident the agent is. This is the legal firewall — the agent
can prepare these, never finalize them alone.
"""
from __future__ import annotations

from enum import Enum

from ..config import ConfidenceThresholds


class Decision(str, Enum):
    AUTO = "auto"
    AUTO_FLAG = "auto_flag"
    DRAFT_HITL = "draft_hitl"
    PAUSE = "pause"


# Actions that always route through a human, regardless of confidence.
# These either finalize the ledger, move money, or speak to outsiders.
HARD_HITL_ACTIONS = frozenset(
    {
        "validate_vendor_bill",   # posts a bill (irreversible)
        "post_journal_entry",     # finalizes an entry (irreversible)
        "register_payment",       # moves money
        "reject_vendor_bill",     # external consequence to a vendor
        "escalate_collection",    # external consequence to a customer
        "send_payment_reminder",  # outbound to a customer (gated separately too)
    }
)


def is_hard_hitl(action: str) -> bool:
    return action in HARD_HITL_ACTIONS


def decide(confidence: float, thresholds: ConfidenceThresholds) -> Decision:
    """Map a confidence score to an escalation decision."""
    if confidence >= thresholds.auto:
        return Decision.AUTO
    if confidence >= thresholds.auto_flag:
        return Decision.AUTO_FLAG
    if confidence >= thresholds.draft_hitl:
        return Decision.DRAFT_HITL
    return Decision.PAUSE


def acts_autonomously(decision: Decision) -> bool:
    """True when the agent may perform the action without waiting for a human."""
    return decision in (Decision.AUTO, Decision.AUTO_FLAG)
