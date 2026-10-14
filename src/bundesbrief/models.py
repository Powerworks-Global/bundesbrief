"""
Core data contracts: the extracted parliamentary affair, and the Trust Contract
bound to it. See docs/adrs/ADR-001 for why this is a separate layer from extraction.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_serializer


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
    """Contextual health signals accompanying an extraction, not the extraction itself.

    THE APERTUS FIELDS — read before touching the three ``apertus_*`` fields:

    * ``apertus_agreement_score`` defaults to a NEUTRAL 1.0: a code path that
      never ran the cross-check must behave exactly as it did before the
      dimension existed ("not penalised"), and the deterministic scoring path
      indeed ignores the value unless the cross-check actually ran. The
      default NEVER means "verified as fully agreeing".
    * What makes "measured" identifiable is ``apertus_backend``: it is
      ``None`` when nobody ever measured agreement, the model tag when an
      Apertus run produced the score, a ``stub:`` label when the offline
      stub produced it, and a ``not-run:`` marker (with the reason) when an
      attempted cross-check failed. See docs/adrs/ADR-003.
    * Ledger wire format: when ``apertus_backend`` is ``None`` all three
      ``apertus_*`` keys are OMITTED from serialization (see the model
      serializer below), so records that never had the dimension hash and
      verify byte-for-byte as before — the hash chain over pre-existing
      ledgers stays intact (the landmine recorded in ADR-002).
    """

    fields_expected: int = Field(..., description="How many fields the schema requires")
    fields_found: int = Field(..., description="How many fields the extractor actually populated")
    ocr_noise_ratio: float = Field(
        ..., ge=0.0, le=1.0, description="Fraction of characters flagged as low-confidence OCR/parse artifacts"
    )
    source_age_days: float = Field(..., ge=0.0, description="Age of the source document in days")
    max_acceptable_age_days: float = Field(
        default=3650.0, description="Beyond this, staleness alone should degrade confidence"
    )
    apertus_agreement_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Fourth-dimension signal: fraction of extracted field values the "
        "cross-check backend found corroborated by the source text. Default 1.0 is "
        "NEUTRAL (cross-check not run -> no penalty), not a claim of verified agreement.",
    )
    apertus_backend: Optional[str] = Field(
        default=None,
        description="What produced apertus_agreement_score: a model tag, a 'stub:' label, "
        "or a 'not-run:' marker with the failure reason. None = never measured.",
    )
    apertus_discrepancies: Optional[list[str]] = Field(
        default=None, description="Field-level disagreements reported by the cross-check backend."
    )

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        """Omit the apertus_* keys entirely for records that were never measured.

        This is what lets a new optional dimension join a hash-chained ledger
        without retroactively invalidating a single existing entry: an
        unmeasured telemetry vector serializes byte-for-byte as it did before
        the dimension existed, so every historical entry re-hashes to the
        value it was appended with. Pinned by tests/test_ledger_legacy_chain.py.
        """
        data = handler(self)
        if self.apertus_backend is None:
            for key in ("apertus_agreement_score", "apertus_backend", "apertus_discrepancies"):
                data.pop(key, None)
        return data


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
