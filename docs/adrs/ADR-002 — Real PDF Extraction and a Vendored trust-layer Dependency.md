# ADR-002: Real PDF Extraction via PyMuPDF, and Trust Scoring Delegated to the `trust-layer` Package

**Status:** Accepted
**Date:** 2026-10-12 (this record revised 2026-10-13 before merge — see Revision History)
**Deciders:** William Power
**Project:** Bundesbrief (openparla challenge)
**Supersedes in part:** ADR-001 — only its recorded scope limitation ("this MVP operates on already-extracted plain text, not raw PDF bytes"). ADR-001's core decision — the decoupled Trust Contract as a separate layer — stands unchanged and is in fact made more concrete by this one.

---

## Context

ADR-001 deliberately deferred real PDF layout parsing to validate the trust-scoring architecture first. `ROADMAP.md` called closing that gap "the single biggest gap between 'architecture demo' and 'actually solves openparla's brief'."

A sibling project, [`pdf-extract`](https://github.com/Willpower-hadisfar/pdf-extract), built the missing mechanism: real field extraction from PDF bytes, plus a more rigorous noise heuristic with named, inspectable sub-scores (garbage ratio, lone-character ratio, replacement-character ratio, OCR-substitution ratio). It also integrated with the standalone [`trust-layer`](https://github.com/Willpower-hadisfar/trust-layer) package, whose `Dimension` normalisers exposed a scoring bug this project was exposed to: `trust-layer` (and this repo's own `trust.py`) blend weighted signals where a *higher* normalised value means *more* confident — so a raw noise metric (higher = worse) must be registered **inverted** (`1.0 - raw`) or a noisier document scores as *more* confident.

Three constraints shaped the options:

1. **Installability.** `trust-layer` lives in a private repository. A forge-address dependency would make this submission uninstallable for judges and strangers — and this repo has no CI that would fail loudly.
2. **The ledger's hash chain.** `bundesbrief.ledger` hashes `TrustContract.model_dump_json() + previous_hash` per entry. Changing the hashed record's wire format retroactively invalidates every existing chain (demonstrated here: one added optional field broke a 900-entry chain). The unit tests cannot catch this — they all build fresh chains — so a pre-built 900-entry chain was built and verified **before** the swap, and that same file re-verified byte-identical after the change.
3. **Robustness and cost.** An early measurement on eighteen real cantonal documents found the `pdfplumber` mechanism at ~47× the per-page cost of the plain-text alternative, crashing outright on two documents where the alternative crashed on none.

### Revision History

*This record was first written on 2026-10-12 selecting `pdfplumber` (the engine the `pdf-extract` sibling project shipped). Before this pull request merged, the maintainer overruled that engine choice on the strength of their own benchmark on this project's real cantonal PDFs — PyMuPDF measured ~47× faster per page with zero crashes where pdfplumber crashed on two documents — and the engine was swapped to PyMuPDF inside the same pull request. The swap was then re-measured rather than assumed (numbers below). The rest of the record — the vendoring decision, the inversion, the ledger non-swap — is unchanged from the first revision.*

## Considered Options

| Evaluation Metric | Keep text-only stub | PyMuPDF real extraction (Chosen) | pdfplumber real extraction | Full OCR (pytesseract + pdf2image) |
|---|---|---|---|---|
| Solves openparla's brief | No — defers the actual parsing step | Yes for PDFs with a text layer (born-digital and already-OCR'd) | Yes, same scope | Yes, also raw scans |
| Speed on real cantonal PDFs | baseline | **1.5 ms/page measured (see below)** | 46.8 ms/page on the same set (~31× slower) | much slower |
| Crash surface on real PDFs | none | none observed (contained regardless) | none observed on the re-measurement set; earlier set: 2 crashes | larger dependency-chain surface |
| Dependency weight | none | wheel with bundled MuPDF core | pure-Python (`pdfminer.six`) | system binaries, heavy |

### Re-measurement on real cantonal documents (not assumed)

Eighteen real Canton of Zurich parliamentary PDFs (20 KB–2.1 MB, 164 pages total) fetched live through the source this project targets — `api.openparldata.ch` affairs → document links → `notes.zh.ch` — timed page-by-page with both engines on 2026-10-13:

- **PyMuPDF: 244 ms total / 1.49 ms/page median** vs **pdfplumber: 7,682 ms / 46.84 ms/page** over the identical 164 pages — **31.5× faster in total, 38× median of per-document per-page ratios** (min 1.8×, max 63×). The captain's ~47×-per-page advantage reproduces in direction and order of magnitude on documents reached here; the exact multiplier does not (31.5× total on this set).
- **Crashes: neither engine crashed on these 18 documents**, so the earlier "pdfplumber crashed on two" fact did not reproduce on this particular fetch; containment is kept regardless because real corpora keep surprising parsers either way.
- **Zero text:** one document (`doc03.pdf`, a scan) yields 0 characters from both engines — it comes back as a recorded, scored-empty outcome through `extract_pdf`/`process_pdf`, not an exception.

| Dependency question (trust-layer) | Keep local copies | Forge-address dependency | Vendored `trust_layer` (Chosen) |
|---|---|---|---|
| Judges can `make install` | Yes | **No** — private repo, no read access | Yes |
| Real library, not a hand-maintained copy | No | Yes | Yes (verbatim copy at a pinned commit) |
| Reversible later | — | — | Yes — one directory swap once upstream is public |

## Decision

1. **`bundesbrief.extraction` now parses real PDF bytes** via **PyMuPDF** (`extract_pages`/`extract_pdf`), keeping the domain surface — the Swiss field patterns, `ExtractionResult`, `extract()` for text — intact underneath. `bundesbrief.pipeline.process_pdf` is the new raw-PDF entrypoint. The old noise-ratio regex is replaced by the named-sub-score heuristic in `bundesbrief.noise` (from `pdf-extract`; the field-extraction *design* carries over, the engine does not).
2. **Malformed documents fail as recorded outcomes.** `extract_pdf` contains *any* parser exception in `ExtractionResult.error` (worst-case noise reading, no affair); `process_pdf` returns `None` for it. Pinned by `tests/test_pdf_extraction.py::TestMalformedPdfRecordedNotRaised`.
3. **`bundesbrief.trust` delegates scoring to the real `trust_layer.ConfidenceScorer`** with the noise dimension registered inverted (`normalise=lambda raw: 1.0 - raw`). This module keeps only the domain adaptation.
4. **`trust_layer` is vendored verbatim** at `src/trust_layer/` (commit `cf91a55`), not declared as a forge dependency — see `src/trust_layer/VENDORED.md`. Follow-up: replace with a pinned public dependency once the upstream repo is public or on PyPI.
5. **`bundesbrief.ledger` is deliberately NOT swapped** to `trust_layer.ledger`: the two ledgers hash different entry formats, so adopting the library's format would retroactively break every existing chain — the exact failure mode this repository has already reproduced. The local module is a wire-compatibility façade, not a duplicate of library logic. Gate evidence: a 900-entry chain built with the pre-change code verified `True`, and verified `True` again — byte-identical file — after the swap.

## Consequences

- **Positive**: the roadmap's "single biggest gap" is closed for PDFs that have a text layer; the noise score is now explainable (sub-scores exposed on `ExtractionResult.noise`); confidence ordering by noise is guaranteed by `tests/test_trust_inversion.py`, which pins both the property (noisier → lower) and the uninverted contrast.
- **Positive**: a fresh clone installs with `make install` alone — no credentials, no forge access.
- **Positive**: at ~1.5 ms/page on real cantonal documents, national-scale nightly re-ingestion is comfortably within reach.
- **Negative, accepted**: a PDF with **no text layer at all** (a raw scan) yields no fields — genuine OCR remains open in `ROADMAP.md`.
- **Negative, accepted**: two vendored copies to keep fresh (`trust_layer`, `bundesbrief.noise` ← `pdf_extract.noise`); mitigated by "do not edit locally, re-vendor" and the de-vendoring follow-up.
- **Honest caveat**: the noisier-scores-lower property is registration-dependent by design — `trust_layer` applies whichever normaliser it is handed. The correctness lives in the registration in `trust.py`, and the suite pins the registration itself, not just the library's wiring.
