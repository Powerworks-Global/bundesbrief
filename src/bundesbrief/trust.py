"""
The actual Truth Layer: turns an ExtractionResult's telemetry into a single
confidence score, then wraps it in a TrustContract the API layer can act on.

Scoring is a weighted blend of three independent signals rather than one
pass/fail check — see docs/adrs/ADR-001 for why each signal is scored
separately instead of a single "did extraction succeed" boolean.
"""

from __future__ import annotations

import uuid

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
    score = (
        _SCHEMA_COMPLETENESS_WEIGHT * schema_completeness(telemetry)
        + _NOISE_PENALTY_WEIGHT * noise_score(telemetry)
        + _FRESHNESS_WEIGHT * freshness_score(telemetry)
    )
    return round(min(max(score, 0.0), 1.0), 4)


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
