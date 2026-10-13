"""The public façade: tie the scorer, gate and ledger together.

``TrustLayer.evaluate`` runs a record through the three stages and returns a
``Decision``; if a ledger is configured, the decision is also appended to it
(and the decision carries the resulting entry hash).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .confidence import ConfidenceScorer, Dimension, Confidence
from .gate import Gate, Verdict
from .ledger import Ledger, LedgerEntry


class EvaluationError(Exception):
    """Raised when evaluation cannot proceed (e.g. no valid dimensions)."""


@dataclass(frozen=True)
class Decision:
    """The outcome of evaluating one record.

    Attributes:
        record_id:   The caller-supplied stable identifier.
        score:       Overall confidence in [0, 1].
        verdict:     ``act``, ``suggest`` or ``halt``.
        breakdown:   Per-dimension normalised values.
        weights:     The normalised (sum-to-1) weights actually applied.
        ledger_hash: The hash of the appended ledger entry, or ``None`` when
                     no ledger is configured.
    """

    record_id: str
    score: float
    verdict: Verdict
    breakdown: Mapping[str, float] = field(default_factory=dict)
    weights: Mapping[str, float] = field(default_factory=dict)
    ledger_hash: Optional[str] = None


class TrustLayer:
    """Wrap an ingestion step with score -> gate -> ledger.

    Args:
        ledger:      Optional ``Ledger``; when given, every decision is
                     appended and its hash returned.
        dimensions:  Optional scorer configuration (defaults to
                     completeness/noise/freshness at 0.5/0.3/0.2). Pass a
                     mapping of name -> weight or name -> ``Dimension``.
        scorer:      Optional pre-built ``ConfidenceScorer``; overrides
                     ``dimensions`` if both are given.
        act_at:      Score threshold for ``act`` (default 0.8).
        suggest_at:  Score threshold for ``suggest`` (default 0.5).
    """

    def __init__(
        self,
        ledger: Ledger | None = None,
        dimensions: Mapping[str, Dimension | float] | None = None,
        scorer: ConfidenceScorer | None = None,
        act_at: float = 0.8,
        suggest_at: float = 0.5,
    ):
        self.ledger = ledger
        self.scorer = scorer if scorer is not None else ConfidenceScorer(dimensions)
        self.gate = Gate(act_at=act_at, suggest_at=suggest_at)

    def evaluate(
        self,
        record_id: str,
        metrics: Mapping[str, float],
        *,
        extra: Mapping[str, Any] | None = None,
        log: bool = True,
    ) -> Decision:
        """Score ``metrics``, gate the result, and (optionally) log it.

        Args:
            record_id: Stable identifier for the record.
            metrics:   Mapping of dimension-name -> raw metric.
            extra:     Optional extra data to record in the ledger payload.
            log:       Whether to append to the ledger (default True; ignored
                       if no ledger is configured).
        """
        confidence: Confidence = self.scorer.score(metrics)
        verdict: Verdict = self.gate.decide(confidence.score)

        ledger_hash: Optional[str] = None
        if self.ledger is not None and log:
            payload: dict[str, Any] = {
                "score": confidence.score,
                "verdict": verdict.value,
                "breakdown": dict(confidence.breakdown),
                "weights": dict(confidence.weights),
            }
            if extra:
                payload["extra"] = extra
            entry: LedgerEntry = self.ledger.append(record_id, payload)
            ledger_hash = entry.hash

        return Decision(
            record_id=record_id,
            score=confidence.score,
            verdict=verdict,
            breakdown=dict(confidence.breakdown),
            weights=dict(confidence.weights),
            ledger_hash=ledger_hash,
        )