"""The personality layer — tone applied to human-facing messages only.

Per the architecture doc: personality is a *layer, not a core*. It NEVER
touches ledger data, amounts, account codes, or anything posted to Odoo's
financial records. It only re-tones notifications and summaries aimed at
the internal finance team.

Hard safety rule: anything that will reach an EXTERNAL party (a customer,
a vendor) is always rendered professionally, even if the workspace has a
playful mode enabled. Trust comes from accuracy, not jokes.
"""
from __future__ import annotations

import random

from ..config import PersonalityMode


class Personality:
    def __init__(self, mode: PersonalityMode = PersonalityMode.PROFESSIONAL, seed: int | None = None):
        self.mode = mode
        self._rng = random.Random(seed)

    def render(self, message: str, *, external_facing: bool = False) -> str:
        """Re-tone an internal message. External messages stay professional."""
        if external_facing or self.mode == PersonalityMode.PROFESSIONAL:
            return message
        if self.mode == PersonalityMode.FRIENDLY:
            return self._friendly(message)
        return self._genz(message)

    # ---- tone implementations ---- #
    def _friendly(self, message: str) -> str:
        opener = self._rng.choice(["Hey team!", "Quick one —", "Heads up:"])
        closer = self._rng.choice(["Let me know if anything looks off. 🙂", "Happy to dig deeper.", "On it."])
        return f"{opener} {message} {closer}"

    def _genz(self, message: str) -> str:
        # Tasteful, opt-in flair for internal channels. Deliberately light —
        # the facts come through unchanged; only the wrapper has vibes.
        opener = self._rng.choice(
            ["ok finance besties 💅", "no cap,", "lowkey heads up —", "the books said:"]
        )
        closer = self._rng.choice(
            ["that's the tea ☕", "we move 🫡", "slay, ledger stays clean ✨", "it's giving balanced books 📚"]
        )
        return f"{opener} {message} {closer}"

    def confidence_note(self, confidence: float) -> str:
        """A short, mode-appropriate gloss on a confidence score."""
        pct = f"{confidence:.0%}"
        if self.mode == PersonalityMode.GENZ:
            if confidence >= 0.9:
                return f"confidence {pct} — fully locked in fr"
            if confidence >= 0.7:
                return f"confidence {pct} — pretty sure but double-check ✌️"
            return f"confidence {pct} — sus, want a human on this"
        if self.mode == PersonalityMode.FRIENDLY:
            return f"I'm about {pct} sure on this one."
        return f"Confidence: {pct}."
