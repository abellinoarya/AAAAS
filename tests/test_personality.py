"""The personality layer: tone in, facts unchanged, external stays professional."""
from __future__ import annotations

from aaaas.agent.personality import Personality
from aaaas.config import PersonalityMode


def test_professional_is_passthrough():
    p = Personality(PersonalityMode.PROFESSIONAL)
    msg = "Invoice INV/1 is 30 days overdue."
    assert p.render(msg) == msg


def test_genz_wraps_but_preserves_facts():
    p = Personality(PersonalityMode.GENZ, seed=1)
    msg = "Invoice INV/1 is 30 days overdue."
    out = p.render(msg)
    assert msg in out          # the facts survive verbatim
    assert out != msg          # but the wrapper changed


def test_external_facing_is_always_professional():
    for mode in (PersonalityMode.FRIENDLY, PersonalityMode.GENZ):
        p = Personality(mode, seed=1)
        msg = "Please arrange payment for invoice INV/1."
        assert p.render(msg, external_facing=True) == msg


def test_confidence_note_mentions_percentage():
    p = Personality(PersonalityMode.PROFESSIONAL)
    assert "90%" in p.confidence_note(0.9)
