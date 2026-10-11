"""
FastAPI surface — API-first per the OpenParlData.ch inspiration (free OpenAPI
docs at /docs). Serves the sample-data pipeline run on startup; wiring a real
scraper against live cantonal parliament PDFs is explicitly future work, see
ROADMAP.md.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException

from bundesbrief.ledger import Ledger
from bundesbrief.models import TrustContract
from bundesbrief.pipeline import process_sample_data

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "sample_affairs"
LEDGER_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ledger.jsonl"

app = FastAPI(
    title="Bundesbrief",
    description="A confidence/truth layer over extracted Swiss parliamentary documents.",
    version="0.1.0",
)

_contracts: dict[str, TrustContract] = {}


@app.on_event("startup")
def _run_pipeline_on_startup() -> None:
    if LEDGER_PATH.exists():
        LEDGER_PATH.unlink()  # fresh ledger per demo run
    for contract in process_sample_data(DATA_DIR, LEDGER_PATH):
        _contracts[contract.affair_id] = contract


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


@app.get("/ledger/verify")
def verify_ledger() -> dict:
    """Walks the hash chain end to end — proves the justification ledger hasn't been tampered with."""
    ledger = Ledger(LEDGER_PATH)
    return {"valid": ledger.verify(), "entries": sum(1 for _ in LEDGER_PATH.open(encoding="utf-8")) if LEDGER_PATH.exists() else 0}
