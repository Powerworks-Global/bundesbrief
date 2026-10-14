"""
FastAPI surface — API-first per the OpenParlData.ch inspiration (free OpenAPI
docs at /docs). Serves the sample-data pipeline run on startup; wiring a real
scraper against live cantonal parliament PDFs is explicitly future work, see
ROADMAP.md.

The seeded pipeline runs the Apertus cross-check through the env switch
(BUNDESBRIEF_REAL_BACKENDS=1 for the real model; deterministic stub by
default — see bundesbrief.apertus_crosscheck). The startup banner names
which backend produced the numbers.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException

from bundesbrief.apertus_crosscheck import get_crosscheck_backend, log_backend
from bundesbrief.ledger import Ledger
from bundesbrief.models import TrustContract
from bundesbrief.pipeline import SampleOutcome, process_sample_data_outcomes

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "sample_affairs"
LEDGER_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ledger.jsonl"

app = FastAPI(
    title="Bundesbrief",
    description="A confidence/truth layer over extracted Swiss parliamentary documents.",
    version="0.1.0",
)

_contracts: dict[str, TrustContract] = {}
_outcomes: dict[str, SampleOutcome] = {}


@app.on_event("startup")
def _run_pipeline_on_startup() -> None:
    if LEDGER_PATH.exists():
        LEDGER_PATH.unlink()  # fresh ledger per demo run
    backend = get_crosscheck_backend()
    log_backend(backend)  # names the backend behind every seeded cross-check number
    for outcome in process_sample_data_outcomes(DATA_DIR, LEDGER_PATH):
        _contracts[outcome.contract.affair_id] = outcome.contract
        _outcomes[outcome.contract.affair_id] = outcome


@app.get("/affairs")
def list_affairs() -> list[dict]:
    """Every processed affair with its trust contract and current mode."""
    return [
        {
            "affair_id": c.affair_id,
            "confidence_score": c.confidence_score,
            "mode": c.current_mode.value,
            "is_publication_permitted": c.is_publication_permitted,
        }
        for c in _contracts.values()
    ]


@app.get("/affairs/{affair_id}")
def get_affair(affair_id: str) -> TrustContract:
    contract = _contracts.get(affair_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Unknown affair_id, or it was Halted before a contract existed")
    return contract


@app.get("/affairs/{affair_id}/cross-check")
def get_affair_cross_check(affair_id: str) -> dict:
    """The Apertus cross-check signal recorded for one affair, from the ledger-
    backed contract — with its ``backend`` label, so a stub score and a
    measured model score are distinguishable from the response alone.

    If the cross-check did not run for this record, the response says so and
    why (``ran: false``); it never invents a score.
    """
    contract = _contracts.get(affair_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Unknown affair_id, or it was Halted before a contract existed")
    telemetry = contract.telemetry
    if telemetry.apertus_backend is None:
        return {"affair_id": affair_id, "ran": False, "reason": "no cross-check was performed for this record"}
    ran = not telemetry.apertus_backend.startswith("not-run:")
    payload: dict = {
        "affair_id": affair_id,
        "ran": ran,
        "agreement_score": telemetry.apertus_agreement_score,
        "backend": telemetry.apertus_backend,
        "discrepancies": telemetry.apertus_discrepancies or [],
        "note": (
            "stub harness-validation figure, NOT a model measurement"
            if telemetry.apertus_backend.startswith("stub:")
            else "measured by the real Apertus (quantised) backend"
            if ran
            else f"cross-check did not run: {telemetry.apertus_backend}"
        ),
    }
    if not ran:
        payload.pop("agreement_score")
        payload["reason"] = telemetry.apertus_backend
    return payload


@app.get("/ledger/verify")
def verify_ledger() -> dict:
    """Walks the hash chain end to end — proves the justification ledger hasn't been tampered with."""
    ledger = Ledger(LEDGER_PATH)
    return {"valid": ledger.verify(), "entries": sum(1 for _ in LEDGER_PATH.open(encoding="utf-8")) if LEDGER_PATH.exists() else 0}
