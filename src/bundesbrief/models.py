"""
Core data contracts: the extracted parliamentary affair, and the Trust Contract
bound to it. See docs/adrs/ADR-001 for why this is a separate layer from extraction.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class AgentExecutionMode(str, Enum):
    """What a downstream agent/consumer is permitted to do with this record."""

    ACT = "ACT"  # confidence clears the bar — safe to publish/consume autonomously
    SUGGEST = "SUGGEST"  # degraded — route to human review before publishing
    HALT = "HALT"  # breached the floor — do not publish, log the failure


class ParliamentaryAffair(BaseModel):
    """A single extracted record — the semantic-layer output this wraps a trust score around."""

    affair_id: str
    title: str
    canton: str
    status: str
    date: str
    source_url: str = ""


class TrustTelemetryVector(BaseModel):
    """Contextual health signals accompanying an extraction, not the extraction itself."""

    fields_expected: int = Field(..., description="How many fields the schema requires")
    fields_found: int = Field(..., description="How many fields the extractor actually populated")
    ocr_noise_ratio: float = Field(
        ..., ge=0.0, le=1.0, description="Fraction of characters flagged as low-confidence OCR/parse artifacts"
    )
    source_age_days: float = Field(..., ge=0.0, description="Age of the source document in days")
    max_acceptable_age_days: float = Field(
        default=3650.0, description="Beyond this, staleness alone should degrade confidence"
    )


class TrustExecutionPolicy(BaseModel):
    """Configurable thresholds governing the Act / Suggest / Halt transition."""

    act_threshold: float = Field(default=0.90, ge=0.0, le=1.0)
    suggest_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    halt_threshold: float = Field(default=0.69, ge=0.0, le=1.0)

    def evaluate(self, confidence_score: float) -> AgentExecutionMode:
        if confidence_score >= self.act_threshold:
            return AgentExecutionMode.ACT
        if confidence_score >= self.suggest_threshold:
            return AgentExecutionMode.SUGGEST
        return AgentExecutionMode.HALT


class TrustContract(BaseModel):
    """
    The machine-readable confidence layer bound to one extracted affair.
    Computed at the moment of consumption, not on a batch schedule — see
    trust.compute_confidence() for the scoring function this wraps.
    """

    contract_id: str
    affair_id: str
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    evaluated_at: datetime
    telemetry: TrustTelemetryVector
    policy: TrustExecutionPolicy
    payload_hash: str

    @property
    def current_mode(self) -> AgentExecutionMode:
        return self.policy.evaluate(self.confidence_score)

    @property
    def is_publication_permitted(self) -> bool:
        return self.current_mode != AgentExecutionMode.HALT


def hash_payload(affair: ParliamentaryAffair) -> str:
    """SHA-256 over the canonical JSON form — the justification-ledger anchor, not a secret."""
    return hashlib.sha256(affair.model_dump_json().encode("utf-8")).hexdigest()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
