"""
The actual Truth Layer: turns an ExtractionResult's telemetry into a single
confidence score, then wraps it in a TrustContract the API layer can act on.

Scoring itself is *not* reimplemented here any more — it delegates to the
real `trust_layer` package (vendored under `src/trust_layer/`, see
`src/trust_layer/VENDORED.md`) via its `ConfidenceScorer` and `Dimension`
abstraction. This module keeps only the domain adaptation: mapping the
parliamentary telemetry vector onto trust_layer's raw metrics.

THE NOISE INVERSION — do not "simplify" this away:
trust_layer's default normaliser treats a *higher* raw metric as *better*.
A raw noise score is the opposite (higher = noisier = worse), so the noise
dimension is registered with `normalise=lambda raw: 1.0 - raw`. Without
that inversion a noisier document would wrongly score as MORE confident.
`tests/test_trust_inversion.py` proves the property end to end on real
generated PDFs and shows the contrast if the dimension were registered
uninverted. See docs/adrs/ADR-002.
"""

from __future__ import annotations

import uuid

from trust_layer import ConfidenceScorer, Dimension

from bundesbrief.extraction import ExtractionResult
from bundesbrief.models import (
    ParliamentaryAffair,
    TrustContract,
    TrustExecutionPolicy,
    TrustTelemetryVector,
    hash_payload,
    now_utc,
)

# Weights are a starting point, not a tuned model — see ROADMAP.md.
_SCHEMA_COMPLETENESS_WEIGHT = 0.5
_NOISE_PENALTY_WEIGHT = 0.3
_FRESHNESS_WEIGHT = 0.2


def _scorer() -> ConfidenceScorer:
    return ConfidenceScorer(
        {
            "completeness": Dimension("completeness", _SCHEMA_COMPLETENESS_WEIGHT),
            # Inverted: a *lower* raw noise score must mean a *higher*
            # confidence contribution. trust_layer's default normaliser
            # clamps the raw value (higher = better), which would score a
            # noisy document as MORE confident. Flipping it here is the fix.
            "noise": Dimension("noise", _NOISE_PENALTY_WEIGHT, normalise=lambda raw: 1.0 - raw),
            "freshness": Dimension("freshness", _FRESHNESS_WEIGHT),
        }
    )

_SCORER = _scorer()


def schema_completeness(telemetry: TrustTelemetryVector) -> float:
    if telemetry.fields_expected == 0:
        return 0.0
    return min(telemetry.fields_found / telemetry.fields_expected, 1.0)


def noise_score(telemetry: TrustTelemetryVector) -> float:
    """1.0 = clean, 0.0 = unusably noisy."""
    return max(0.0, 1.0 - telemetry.ocr_noise_ratio)


def freshness_score(telemetry: TrustTelemetryVector) -> float:
    """Linear decay to 0 at max_acceptable_age_days — a real deployment would
    want a decay curve tuned per affair type, not linear; see ROADMAP.md."""
    if telemetry.max_acceptable_age_days <= 0:
        return 0.0
    return max(0.0, 1.0 - (telemetry.source_age_days / telemetry.max_acceptable_age_days))


def compute_confidence(telemetry: TrustTelemetryVector) -> float:
    """Blend the three domain signals through trust_layer's real scorer.

    Raw metrics handed to the scorer: completeness and freshness are already
    "higher = better"; raw noise is inverted by the dimension's normaliser
    (module docstring) inside trust_layer's scoring step.
    """
    scorer = _SCORER
    confidence = scorer.score(
        {
            "completeness": schema_completeness(telemetry),
            "noise": telemetry.ocr_noise_ratio,
            "freshness": freshness_score(telemetry),
        }
    )
    return round(confidence.score, 4)


def build_trust_contract(
    affair: ParliamentaryAffair,
    extraction: ExtractionResult,
    source_age_days: float,
    policy: TrustExecutionPolicy | None = None,
) -> TrustContract:
    telemetry = TrustTelemetryVector(
        fields_expected=extraction.fields_expected,
        fields_found=extraction.fields_found,
        ocr_noise_ratio=extraction.ocr_noise_ratio,
        source_age_days=source_age_days,
    )
    confidence = compute_confidence(telemetry)
    return TrustContract(
        contract_id=f"tc-{uuid.uuid4().hex[:12]}",
        affair_id=affair.affair_id,
        confidence_score=confidence,
        evaluated_at=now_utc(),
        telemetry=telemetry,
        policy=policy or TrustExecutionPolicy(),
        payload_hash=hash_payload(affair),
    )
