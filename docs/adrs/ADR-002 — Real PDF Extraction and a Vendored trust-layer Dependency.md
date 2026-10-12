# ADR-002: Real PDF Extraction, and Trust Scoring Delegated to the `trust-layer` Package

**Status:** Accepted
**Date:** 2026-10-12
**Deciders:** William Power
**Project:** Bundesbrief (openparla challenge)
**Supersedes in part:** ADR-001 — only its recorded scope limitation ("this MVP operates on already-extracted plain text, not raw PDF bytes"). ADR-001's core decision — the decoupled Trust Contract as a separate layer — stands unchanged and is in fact made more concrete by this one.

---

## Context

ADR-001 deliberately deferred real PDF layout parsing to validate the trust-scoring architecture first. `ROADMAP.md` called closing that gap "the single biggest gap between 'architecture demo' and 'actually solves openparla's brief'."

A sibling project, [`pdf-extract`](https://github.com/Willpower-hadisfar/pdf-extract), built exactly the missing mechanism: real field extraction from PDF bytes via `pdfplumber`, plus a more rigorous noise heuristic with named, inspectable sub-scores (garbage ratio, lone-character ratio, replacement-character ratio, OCR-substitution ratio). It also integrated with the standalone [`trust-layer`](https://github.com/Willpower-hadisfar/trust-layer) package, whose `Dimension` normalisers exposed a scoring bug this project was exposed to: `trust-layer` (and this repo's own `trust.py`) blend weighted signals where a *higher* normalised value means *more* confident — so a raw noise metric (higher = worse) must be registered **inverted** (`1.0 - raw`) or a noisier document scores as *more* confident.

Three constraints shaped the options:

1. **Installability.** `trust-layer` lives in a private repository. A forge-address dependency would make this submission uninstallable for judges and strangers — and this repo has no CI that would fail loudly.
2. **The ledger's hash chain.** `bundesbrief.ledger` hashes `TrustContract.model_dump_json() + previous_hash` per entry. Changing the hashed record's wire format retroactively invalidates every existing chain (demonstrated here: one added optional field broke a 900-entry chain). The unit tests cannot catch this — they all build fresh chains — so a pre-built 900-entry chain was built and verified **before** the swap, and that same file re-verified byte-identical after the change.
3. **Robustness.** On eighteen real cantonal documents, the `pdfplumber` mechanism measured ~47× the per-page cost of the plain-text alternative and crashed outright on two documents where the alternative crashed on none. The captain chose the mechanism anyway; the obligation is that a malformed document fails as a *recorded outcome*, never as an unhandled exception.

## Considered Options

| Evaluation Metric | Keep text-only stub | pdfplumber real extraction (Chosen) | Full OCR (pytesseract + pdf2image) |
|---|---|---|---|
| Solves openparla's brief | No — defers the actual parsing step | Yes for PDFs with a text layer (born-digital and already-OCR'd) | Yes, also raw scans |
| Crash surface | None | Real — contained via recorded outcomes | Larger dependency-chain surface |
| Dependency weight | none | `pdfplumber` (pure-Python) | system binaries, heavy |
| Per-page cost | baseline | ~3 ms/page measured here (~47× baseline on 18 real cantonal PDFs, accepted) | much higher |

| Dependency question | Keep local copies | Forge-address dependency | Vendored `trust_layer` (Chosen) |
|---|---|---|---|
| Judges can `make install` | Yes | **No** — private repo, no read access | Yes |
| Real library, not a hand-maintained copy | No | Yes | Yes (verbatim copy at a pinned commit) |
| Reversible later | — | — | Yes — one directory swap once upstream is public |

## Decision

1. **`bundesbrief.extraction` now parses real PDF bytes** via `pdfplumber` (`extract_pages`/`extract_pdf`), keeping the domain surface — the Swiss field patterns, `ExtractionResult`, `extract()` for text — intact underneath. `bundesbrief.pipeline.process_pdf` is the new raw-PDF entrypoint. The old noise-ratio regex is replaced by the named-sub-score heuristic in `bundesbrief.noise`.
2. **Malformed documents fail as recorded outcomes.** `extract_pdf` contains *any* parser exception in `ExtractionResult.error` (worst-case noise reading, no affair); `process_pdf` returns `None` for it. Pinned by `tests/test_pdf_extraction.py::TestMalformedPdfRecordedNotRaised`.
3. **`bundesbrief.trust` delegates scoring to the real `trust_layer.ConfidenceScorer`** with the noise dimension registered inverted (`normalise=lambda raw: 1.0 - raw`). This module keeps only the domain adaptation.
4. **`trust_layer` is vendored verbatim** at `src/trust_layer/` (commit `cf91a55`), not declared as a forge dependency — see `src/trust_layer/VENDORED.md`. Follow-up: replace with a pinned public dependency once the upstream repo is public or on PyPI.
5. **`bundesbrief.ledger` is deliberately NOT swapped** to `trust_layer.ledger`: the two ledgers hash different entry formats, so adopting the library's format would retroactively break every existing chain — the exact failure mode this repository has already reproduced. The local module is a wire-compatibility façade, not a duplicate of library logic. Gate evidence: a 900-entry chain built with the pre-change code verified `True`, and verified `True` again — byte-identical file — after the swap.

## Consequences

- **Positive**: the roadmap's "single biggest gap" is closed for PDFs that have a text layer; the noise score is now explainable (sub-scores exposed on `ExtractionResult.noise`); confidence ordering by noise is guaranteed by `tests/test_trust_inversion.py`, which pins both the property (noisier → lower) and the uninverted contrast.
- **Positive**: a fresh clone installs with `make install` alone — no credentials, no forge access.
- **Negative, accepted**: ~3 ms/page measured here on generated documents (parse overhead dominates; ~47× the text path on 18 real cantonal documents per the earlier measurement) — fine at cantonal publication volumes, worth revisiting at national scale.
- **Negative, accepted**: a PDF with **no text layer at all** (a raw scan) yields no fields — genuine OCR remains open in `ROADMAP.md`.
- **Negative, accepted**: two vendored copies to keep fresh (`trust_layer`, `bundesbrief.noise` ← `pdf_extract.noise`); mitigated by "do not edit locally, re-vendor" and the de-vendoring follow-up.
- **Honest caveat**: the noisier-scores-lower property is registration-dependent by design — `trust_layer` applies whichever normaliser it is handed. The correctness lives in the registration in `trust.py`, and the suite pins the registration itself, not just the library's wiring.
