"""Act/Suggest/Halt gating from a confidence score.

A ``Gate`` converts a numeric confidence score into one of three verdicts:

* ``act``     — confidence is high enough to proceed automatically.
* ``suggest`` — confidence is middling; proceed with a human in the loop.
* ``halt``    — confidence is too low; do not act, flag for review.

Thresholds are configurable; the defaults (0.8 / 0.5) match the pattern
this library was extracted from.
"""

from __future__ import annotations

from enum import Enum


class Verdict(str, Enum):
    ACT = "act"
    SUGGEST = "suggest"
    HALT = "halt"


class Gate:
    """Threshold-based Act/Suggest/Halt gate.

    Args:
        act_at:     Scores >= this value are ``act``.
        suggest_at: Scores >= this value (and < act_at) are ``suggest``.
                    Scores below this are ``halt``.
    """

    def __init__(self, act_at: float = 0.8, suggest_at: float = 0.5):
        if not 0.0 <= suggest_at <= act_at <= 1.0:
            raise ValueError("Require 0 <= suggest_at <= act_at <= 1.")
        self.act_at = act_at
        self.suggest_at = suggest_at

    def decide(self, score: float) -> Verdict:
        """Return the verdict for a confidence score in [0, 1]."""
        if score >= self.act_at:
            return Verdict.ACT
        if score >= self.suggest_at:
            return Verdict.SUGGEST
        return Verdict.HALT
