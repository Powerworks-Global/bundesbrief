"""
MVP-scoped extraction: operates on already-OCR'd/plain text, not raw PDF bytes.

Real PDF parsing (pdfplumber/PyMuPDF against actual cantonal parliament PDFs) is
explicitly out of scope for this MVP — see docs/adrs/ADR-001 and ROADMAP.md. The
point of this pass is to validate the trust-scoring architecture against
realistically messy *extracted* text first, not to solve PDF layout parsing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bundesbrief.models import ParliamentaryAffair

EXPECTED_FIELDS = ("affair_id", "title", "canton", "status", "date")

# Deliberately crude pattern set — good enough to demonstrate "did extraction
# actually find this field," not a production parser.
_PATTERNS = {
    "affair_id": re.compile(r"(?:Geschäft|Affair)[-\s]*(?:Nr\.?|ID)?\s*[:#]?\s*([A-Z0-9.\-]+)", re.IGNORECASE),
    "title": re.compile(r"Titel\s*:\s*(.+?)(?:\n|$)", re.IGNORECASE),
    "canton": re.compile(r"Kanton\s*:\s*([A-Za-zÀ-ÿ\-\s]+?)(?:\n|$)", re.IGNORECASE),
    "status": re.compile(r"Status\s*:\s*([A-Za-zÀ-ÿ\-\s]+?)(?:\n|$)", re.IGNORECASE),
    "date": re.compile(r"Datum\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", re.IGNORECASE),
}

# Rough proxy for OCR/parse noise: a run of characters outside normal text ranges.
_NOISE_PATTERN = re.compile(r"[^\x20-\x7EÀ-ſ\n]")


@dataclass
class ExtractionResult:
    affair: ParliamentaryAffair | None
    fields_found: int
    fields_expected: int
    ocr_noise_ratio: float


def extract(raw_text: str, source_url: str = "") -> ExtractionResult:
    """Pull known fields out of raw extracted text, tracking what was actually found."""
    found: dict[str, str] = {}
    for field, pattern in _PATTERNS.items():
        match = pattern.search(raw_text)
        if match:
            found[field] = match.group(1).strip()

    noise_chars = len(_NOISE_PATTERN.findall(raw_text))
    noise_ratio = noise_chars / max(len(raw_text), 1)

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
        ocr_noise_ratio=round(noise_ratio, 4),
    )
