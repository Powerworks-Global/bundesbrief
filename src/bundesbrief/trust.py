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

from bundesbrief.apertus_crosscheck import CrossCheckResult
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

# Fourth-dimension profile, ACTIVE ONLY when a real Apertus measurement is
# attached (see _uses_apertus): the deterministic trio keeps its exact
# internal 0.5/0.3/0.2 ratio, rescaled to share 0.8, and the cross-check
# gets 0.2. Chosen so (a) scores without a model measurement are byte-for-byte
# today's scores, (b) the deterministic pipeline stays authoritative (0.8 of
# the weight), and (c) a model-reported zero agreement caps the score at 0.8
# — below ACT (a full disagreement can block auto-publication, forcing
# Suggest review) but not by itself a HALT. Rationale and falsifier:
# docs/adrs/ADR-003.
_APERTUS_WEIGHT = 0.2
_SCHEMA_COMPLETENESS_WEIGHT_4D = _SCHEMA_COMPLETENESS_WEIGHT * (1.0 - _APERTUS_WEIGHT)  # 0.40
_NOISE_PENALTY_WEIGHT_4D = _NOISE_PENALTY_WEIGHT * (1.0 - _APERTUS_WEIGHT)  # 0.24
_FRESHNESS_WEIGHT_4D = _FRESHNESS_WEIGHT * (1.0 - _APERTUS_WEIGHT)  # 0.16


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


def _scorer_with_apertus() -> ConfidenceScorer:
    return ConfidenceScorer(
        {
            "completeness": Dimension("completeness", _SCHEMA_COMPLETENESS_WEIGHT_4D),
            "noise": Dimension("noise", _NOISE_PENALTY_WEIGHT_4D, normalise=lambda raw: 1.0 - raw),
            "freshness": Dimension("freshness", _FRESHNESS_WEIGHT_4D),
            "apertus_agreement": Dimension("apertus_agreement", _APERTUS_WEIGHT),
        }
    )

_SCORER = _scorer()
_SCORER_4D = _scorer_with_apertus()


def _uses_apertus(telemetry: TrustTelemetryVector) -> bool:
    """True only when a real model measurement produced the agreement score.

    Deliberately narrow: a stub label (harness validation, passes near-
    tautologically on the text path) or a 'not-run:' marker must NOT feed the
    authoritative score — only numbers the model actually measured do. That
    is also what keeps every no-cross-check and stub-only code path scoring
    today's exact numbers, per the trust contract in ADR-003.
    """
    backend = telemetry.apertus_backend
    return backend is not None and not backend.startswith(("stub:", "not-run:"))


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
    """Blend the domain signals through trust_layer's real scorer.

    Raw metrics handed to the scorer: completeness and freshness are already
    "higher = better"; raw noise is inverted by the dimension's normaliser
    (module docstring) inside trust_layer's scoring step.

    Three dimensions — today's exact weights and numbers — unless a real
    Apertus measurement is attached, in which case the rebalanced four-
    dimension profile applies (module constants, ADR-003).
    """
    if _uses_apertus(telemetry):
        scorer = _SCORER_4D
        metrics = {
            "completeness": schema_completeness(telemetry),
            "noise": telemetry.ocr_noise_ratio,
            "freshness": freshness_score(telemetry),
            "apertus_agreement": telemetry.apertus_agreement_score,
        }
    else:
        scorer = _SCORER
        metrics = {
            "completeness": schema_completeness(telemetry),
            "noise": telemetry.ocr_noise_ratio,
            "freshness": freshness_score(telemetry),
        }
    confidence = scorer.score(metrics)
    return round(confidence.score, 4)


def build_trust_contract(
    affair: ParliamentaryAffair,
    extraction: ExtractionResult,
    source_age_days: float,
    policy: TrustExecutionPolicy | None = None,
    cross_check: CrossCheckResult | None = None,
    cross_check_failure: str | None = None,
) -> TrustContract:
    """Compose telemetry, score it, and wrap it in the contract.

    ``cross_check``: a produced CrossCheckResult (stub or real — the backend
    label decides whether it feeds the score, see ``_uses_apertus``).
    ``cross_check_failure``: reason string when an attempted cross-check
    could not run — recorded plainly in the telemetry as a ``not-run:``
    marker; the deterministic score is unaffected either way.
    """
    telemetry = TrustTelemetryVector(
        fields_expected=extraction.fields_expected,
        fields_found=extraction.fields_found,
        ocr_noise_ratio=extraction.ocr_noise_ratio,
        source_age_days=source_age_days,
    )
    if cross_check is not None:
        telemetry.apertus_agreement_score = cross_check.agreement_score
        telemetry.apertus_backend = cross_check.backend
        telemetry.apertus_discrepancies = list(cross_check.discrepancies)
    elif cross_check_failure is not None:
        telemetry.apertus_backend = f"not-run: {cross_check_failure}"
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
