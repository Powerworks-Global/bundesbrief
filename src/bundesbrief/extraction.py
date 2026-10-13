"""
Extraction: real PDF field extraction via PyMuPDF, plus the text-level
field matcher the PDF path reuses.

Historically this module was an MVP stub that operated only on
already-extracted text (deliberately deferring real PDF parsing — see
ADR-001's scope note, superseded by ADR-002). It now carries real PDF
extraction: `extract_pdf()` reads raw PDF bytes through PyMuPDF and matches
the same Swiss parliamentary field patterns against the actual PDF text
layer. The engine is PyMuPDF, chosen over pdfplumber on the maintainer's
cantonal-PDF benchmark (~47x faster per page, zero crashes vs two) and
reproduced on 18 fresh Canton of Zurich documents fetched live via
api.openparldata.ch — see ADR-002 for the measurement.

It is *not* an OCR engine: a PDF with no text layer (a raw scan) yields
empty text and therefore no fields — genuine scans would need
pytesseract/pdf2image, a heavier dependency chain this project
deliberately does not take on.

A malformed or unreadable PDF is a *recorded outcome*, never an
unhandled exception: `extract_pdf()` catches parser failures and returns
an `ExtractionResult` with `error` set, so one broken document cannot
take down a run.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

import pymupdf

from bundesbrief.models import ParliamentaryAffair
from bundesbrief.noise import NoiseScore, noise_score

logger = logging.getLogger(__name__)

EXPECTED_FIELDS = ("affair_id", "title", "canton", "status", "date")

# The domain field patterns are unchanged from the MVP — the real-PDF work
# went underneath them, not into them.
_PATTERNS = {
    "affair_id": re.compile(r"(?:Geschäft|Affair)[-\s]*(?:Nr\.?|ID)?\s*[:#]?\s*([A-Z0-9.\-]+)", re.IGNORECASE),
    "title": re.compile(r"Titel\s*:\s*(.+?)(?:\n|$)", re.IGNORECASE),
    "canton": re.compile(r"Kanton\s*:\s*([A-Za-zÀ-ÿ\-\s]+?)(?:\n|$)", re.IGNORECASE),
    "status": re.compile(r"Status\s*:\s*([A-Za-zÀ-ÿ\-\s]+?)(?:\n|$)", re.IGNORECASE),
    "date": re.compile(r"Datum\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", re.IGNORECASE),
}


@dataclass
class ExtractionResult:
    """Telemetry of one extraction. Plain data — never hashed into the ledger.

    ``error`` is set (and ``affair`` is ``None``) when the document could not
    be parsed at all: a recorded failure, not an exception. ``noise`` carries
    the named sub-scores behind ``ocr_noise_ratio``.
    """

    affair: ParliamentaryAffair | None
    fields_found: int
    fields_expected: int
    ocr_noise_ratio: float
    noise: NoiseScore | None = None
    error: str | None = None


def extract_pages(pdf_path: str) -> List[str]:
    """Return the extracted text of each PDF page, one string per page.

    Pages with no text produce an empty string and are still included, so
    list index + 1 equals the 1-based page number.
    """
    pages: List[str] = []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            pages.append(page.get_text("text") or "")
    return pages


def extract(raw_text: str, source_url: str = "") -> ExtractionResult:
    """Pull known fields out of already-extracted text, tracking what was found.

    Field matching is unchanged from the MVP; the noise estimate is now the
    named-sub-score heuristic from `bundesbrief.noise` rather than the old
    single noise-ratio regex.
    """
    found: dict[str, str] = {}
    for field, pattern in _PATTERNS.items():
        match = pattern.search(raw_text)
        if match:
            found[field] = match.group(1).strip()

    noise = noise_score(raw_text)

    affair = None
    if "affair_id" in found:
        affair = ParliamentaryAffair(
            affair_id=found.get("affair_id", "UNKNOWN"),
            title=found.get("title", ""),
            canton=found.get("canton", ""),
            status=found.get("status", ""),
            date=found.get("date", ""),
            source_url=source_url,
        )

    return ExtractionResult(
        affair=affair,
        fields_found=len(found),
        fields_expected=len(EXPECTED_FIELDS),
        ocr_noise_ratio=round(noise.score, 4),
        noise=noise,
    )


def extract_pdf(pdf_path: str, source_url: str = "") -> ExtractionResult:
    """Extract fields from raw PDF bytes via PyMuPDF.

    A parser failure (malformed PDF, encrypted file, truncated stream,
    unreadable page) is caught and recorded in ``ExtractionResult.error``
    with a worst-case noise reading and no affair — callers get a uniform
    "recorded outcome" shape and never see PyMuPDF exceptions.
    """
    try:
        pages = extract_pages(pdf_path)
    except Exception as exc:  # noqa: BLE001 - the whole point is to contain *any* parser failure
        message = f"{type(exc).__name__}: {exc}"
        logger.warning("PDF extraction failed for %s — recorded, not raised", pdf_path)
        return ExtractionResult(
            affair=None,
            fields_found=0,
            fields_expected=len(EXPECTED_FIELDS),
            ocr_noise_ratio=1.0,
            error=message,
        )
    return extract("\n".join(pages), source_url=source_url or f"file://{pdf_path}")
