"""Wires extraction -> trust scoring -> ledger into one call, for a single source document."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from bundesbrief.extraction import extract
from bundesbrief.ledger import Ledger
from bundesbrief.models import TrustContract
from bundesbrief.trust import build_trust_contract


def process_document(raw_text: str, source_url: str, document_date: date, ledger: Ledger) -> TrustContract | None:
    """Returns None if extraction found nothing resembling an affair at all —
    that's a Halt-before-scoring case, not a low-confidence one."""
    result = extract(raw_text, source_url=source_url)
    if result.affair is None:
        return None

    age_days = (date.today() - document_date).days
    contract = build_trust_contract(result.affair, result, source_age_days=float(age_days))
    ledger.append(contract)
    return contract


def process_sample_data(data_dir: Path, ledger_path: Path) -> list[TrustContract]:
    """Runs every .txt file in data_dir through the pipeline — the MVP demo entrypoint."""
    ledger = Ledger(ledger_path)
    contracts: list[TrustContract] = []
    # Deliberately mismatched dates per sample, to exercise the freshness signal.
    sample_dates = {
        "clean.txt": date(2026, 9, 15),
        "degraded_ocr.txt": date(2026, 8, 2),
        "incomplete_stale.txt": date(1998, 1, 1),
    }
    for path in sorted(data_dir.glob("*.txt")):
        raw_text = path.read_text(encoding="utf-8")
        doc_date = sample_dates.get(path.name, date.today())
        contract = process_document(raw_text, source_url=f"file://{path}", document_date=doc_date, ledger=ledger)
        if contract is not None:
            contracts.append(contract)
    return contracts
