"""Confidence-gated escalation policy and hard HITL rules."""
from __future__ import annotations

from aaaas.agent.confidence import (
    Decision,
    HARD_HITL_ACTIONS,
    acts_autonomously,
    decide,
    is_hard_hitl,
)
from aaaas.config import ConfidenceThresholds


def test_decision_bands():
    t = ConfidenceThresholds()
    assert decide(0.99, t) == Decision.AUTO
    assert decide(0.90, t) == Decision.AUTO
    assert decide(0.80, t) == Decision.AUTO_FLAG
    assert decide(0.60, t) == Decision.DRAFT_HITL
    assert decide(0.40, t) == Decision.PAUSE


def test_acts_autonomously():
    assert acts_autonomously(Decision.AUTO)
    assert acts_autonomously(Decision.AUTO_FLAG)
    assert not acts_autonomously(Decision.DRAFT_HITL)
    assert not acts_autonomously(Decision.PAUSE)


def test_hard_hitl_actions_cover_irreversible_and_external():
    for action in ("validate_vendor_bill", "post_journal_entry",
                   "register_payment", "reject_vendor_bill"):
        assert is_hard_hitl(action)
    assert not is_hard_hitl("match_bill_to_po")
    assert HARD_HITL_ACTIONS  # non-empty
