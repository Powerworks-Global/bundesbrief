"""Shared test helpers: generate real PDF files at runtime with reportlab.

No committed binary PDFs — each test builds a small PDF in a temporary
directory. Mirrors the rigour of the `pdf-extract` source repository's
fixtures (real document bytes, never mocked extraction).
"""

from __future__ import annotations

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# The same field shape `bundesbrief.extraction` knows how to find, laid out
# one field per line like the shipped sample .txt documents.
CLEAN_LINES = [
    "Geschäft Nr: GR-2026-0412",
    "Titel: Motion zur Förderung erneuerbarer Energien im Kanton Zürich",
    "Kanton: Zürich",
    "Status: In Beratung",
    "Datum: 2026-09-15",
]

# The identical five field lines — all present, byte-for-byte the same —
# surrounded by filler carrying the artifacts the noise heuristic detects:
# spaced-out single characters (lone chars) and classic l/1, O/0, S/5 OCR
# substitutions, like a bad scanned-then-OCR'd footer. Field *content* is
# identical to CLEAN_LINES so a confidence comparison isolates noise.
NOISY_LINES = [
    "l 1 O 0 S 5 rn cl l 1 O 0 S 5 rn cl",
    "1 2 3 4 5 6 7 8 9 0 l O S rn cl 1 O S",
    "G e s c h ä f t s v e r z e i c h n i s  d e s  K a n t o n s r a t e s",
    "O f f i c e  d u  c o n s e i l  n ° 1 2 - B e r i c h t 5 2 - l l l",
    "Geschäft Nr: GR-2026-0412",
    "Titel: Motion zur Förderung erneuerbarer Energien im Kanton Zürich",
    "Kanton: Zürich",
    "Status: In Beratung",
    "Datum: 2026-09-15",
    "A m t l i c h e r  B e r i c h t  1 9 9 8 - S e i t e  l O O 5",
]


def write_pdf(path: str, lines: list[str], pages: int = 1) -> str:
    """Write a PDF (one page per `pages` entry) whose text is `lines`.

    Lines are distributed round-robin across pages; every page gets at least
    the header so multi-page documents have per-page text.
    """
    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    per_page = max(len(lines) // pages, 1)
    for page_no in range(pages):
        y = height - 72
        chunk = lines[page_no * per_page : (page_no + 1) * per_page]
        if page_no == pages - 1:  # last page takes any remainder
            chunk = lines[page_no * per_page :]
        for line in chunk:
            c.drawString(72, y, line)
            y -= 20
        c.showPage()
    c.save()
    return str(path)
