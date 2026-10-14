"""Wires extraction -> (optional Apertus cross-check) -> trust scoring -> ledger
into one call, for a single source document.

The cross-check is wired into the real path here (not just unit-tested in
isolation): with the default ``cross_check="auto"`` every document gets its
agreement signal through the env-switched backend — the deterministic stub
on a bare checkout (no network, no model, no daemon), the real Apertus run
when BUNDESBRIEF_REAL_BACKENDS=1. A model failure NEVER takes deterministic
extraction down with it: the document still extracts, still scores on its
deterministic dimensions, and the record says plainly that the cross-check
did not run and why (a ``not-run:`` marker in the telemetry).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal, NamedTuple, Optional, Union

from bundesbrief.apertus_crosscheck import CrossCheckError, CrossCheckResult, get_crosscheck_backend
from bundesbrief.extraction import extract, extract_pdf
from bundesbrief.ledger import Ledger
from bundesbrief.models import ParliamentaryAffair, TrustContract
from bundesbrief.trust import build_trust_contract

CROSSCHECK_AUTO = "auto"
CrossCheckOption = Union[Literal["auto"], CrossCheckResult, None]


def _run_crosscheck(
    affair, source_text: str, cross_check: CrossCheckOption
) -> tuple[Optional[CrossCheckResult], Optional[str]]:
    """Resolve the cross-check option into (result, failure_reason).

    ``None``   -> not attempted; the record stays exactly as it was before
                  this dimension existed (apertus_* keys omitted).
    ``"auto"`` -> ask the env-switched backend (stub unless
                  BUNDESBRIEF_REAL_BACKENDS=1); any backend failure is
                  contained and returned as a reason string — deterministic
                  scoring proceeds untouched.
    a result   -> used as given (e.g. a pre-computed real measurement).
    """
    if cross_check is None:
        return None, None
    if isinstance(cross_check, CrossCheckResult):
        return cross_check, None
    backend = get_crosscheck_backend()
    try:
        return backend.compare(affair, source_text), None
    except CrossCheckError as exc:
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001 - containment IS the contract: no model failure may kill extraction
        return None, f"unexpected {type(exc).__name__}: {exc}"


def process_document(
    raw_text: str,
    source_url: str,
    document_date: date,
    ledger: Ledger,
    cross_check: CrossCheckOption = CROSSCHECK_AUTO,
) -> TrustContract | None:
    """Returns None if extraction found nothing resembling an affair at all —
    that's a Halt-before-scoring case, not a low-confidence one."""
    result = extract(raw_text, source_url=source_url)
    if result.affair is None:
        return None

    cc_result, cc_failure = _run_crosscheck(result.affair, raw_text, cross_check)
    age_days = (date.today() - document_date).days
    contract = build_trust_contract(
        result.affair,
        result,
        source_age_days=float(age_days),
        cross_check=cc_result,
        cross_check_failure=cc_failure,
    )
    ledger.append(contract)
    return contract


def process_pdf(
    pdf_path: str,
    document_date: date,
    ledger: Ledger,
    source_url: str = "",
    cross_check: CrossCheckOption = CROSSCHECK_AUTO,
) -> TrustContract | None:
    """Real-PDF entrypoint: raw PDF bytes -> extraction -> TrustContract.

    A malformed/unreadable PDF is a recorded outcome, never an exception:
    `extract_pdf` contains parser failures in `ExtractionResult.error` (and
    logs the reason), and this function then returns `None` — a
    halt-before-scoring case, like an extraction that finds no affair at all.
    The Apertus cross-check (module docstring) runs against the PDF's text
    layer and is contained the same way: it can never fail a document.
    """
    result = extract_pdf(pdf_path, source_url=source_url)
    if result.error is not None or result.affair is None:
        return None

    cc_result, cc_failure = _run_crosscheck(result.affair, result.source_text, cross_check)
    age_days = (date.today() - document_date).days
    contract = build_trust_contract(
        result.affair,
        result,
        source_age_days=float(age_days),
        cross_check=cc_result,
        cross_check_failure=cc_failure,
    )
    ledger.append(contract)
    return contract


class SampleOutcome(NamedTuple):
    """One seeded sample: what was decided, from what fields, against what text."""

    contract: TrustContract
    affair: ParliamentaryAffair
    source_text: str


def process_sample_data(
    data_dir: Path, ledger_path: Path, cross_check: CrossCheckOption = CROSSCHECK_AUTO
) -> list[TrustContract]:
    """Runs every .txt file in data_dir through the pipeline — the MVP demo entrypoint."""
    return [o.contract for o in process_sample_data_outcomes(data_dir, ledger_path, cross_check)]


def process_sample_data_outcomes(
    data_dir: Path, ledger_path: Path, cross_check: CrossCheckOption = CROSSCHECK_AUTO
) -> list[SampleOutcome]:
    """Same run as process_sample_data, additionally returning the extracted
    affair and raw source text per document, so the API/MCP surfaces can show
    each record's cross-check signal (with its backend label) on request."""
    ledger = Ledger(ledger_path)
    outcomes: list[SampleOutcome] = []
    # Deliberately mismatched dates per sample, to exercise the freshness signal.
    sample_dates = {
        "clean.txt": date(2026, 9, 15),
        "degraded_ocr.txt": date(2026, 8, 2),
        "incomplete_stale.txt": date(1998, 1, 1),
    }
    for path in sorted(data_dir.glob("*.txt")):
        raw_text = path.read_text(encoding="utf-8")
        doc_date = sample_dates.get(path.name, date.today())
        result = extract(raw_text, source_url=f"file://{path}")
        contract = process_document(
            raw_text, source_url=f"file://{path}", document_date=doc_date, ledger=ledger, cross_check=cross_check
        )
        if contract is not None and result.affair is not None:
            outcomes.append(SampleOutcome(contract=contract, affair=result.affair, source_text=raw_text))
    return outcomes
