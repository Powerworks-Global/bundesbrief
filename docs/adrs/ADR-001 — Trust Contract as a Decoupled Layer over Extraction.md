# ADR-001: Trust Contract as a Decoupled Confidence Layer, Not an Extraction-Quality Check

**Status:** Accepted
**Date:** 2026-10-11
**Deciders:** William Power
**Project:** Bundesbrief (openparla challenge)

---

## Context

openparla's brief is to extract Swiss parliamentary affairs from inconsistent PDF layouts into one structured, searchable format while preserving links to the original source. The naive version of this is a single extraction pipeline: parse the PDF, populate a schema, publish the record. That pipeline has a view of the *structured output* it produces, but no mechanism for knowing — and surfacing to a downstream consumer — whether a given extraction was actually faithful to its source, or a confident-looking guess built from a partially-corrupted or stale document.

Two architectural options were considered for addressing this.

1. **Extraction-quality gate inline with the parser**: the extractor itself refuses to emit a record below some hard-coded completeness threshold.
2. **A decoupled Trust Contract**, computed as a separate step after extraction, carrying its own telemetry vector (schema completeness, OCR/parse noise, source staleness) and evaluated against a configurable Act/Suggest/Halt policy — independent of the extractor's own internal logic.

## Decision Drivers

- **Extensibility**: new telemetry signals (cross-reference against a raw page image, source-reliability history per canton) need to be addable without touching the extraction code itself.
- **Policy configurability per consumer**: a research use case might tolerate a lower confidence floor than a public-facing "official record" view — a single hard-coded threshold inside the extractor can't express that.
- **Auditability**: a downstream consumer disputing a published record needs to see *why* it was trusted, not just that it was — a Trust Contract object is a natural evidence artifact; an inline boolean check inside the parser isn't.
- **This exact separation already proved out**: the related [Rütli](https://github.com/Powerworks-Global/ruetli) submission decouples its policy engine from its agent runner for the same reasons (avoiding a single point of failure wired into the critical path, and making the authorization decision independently auditable) — see Rütli's own ADR-001.

## Considered Options

| Evaluation Metric | Inline Extraction-Quality Gate | Decoupled Trust Contract (Chosen) |
|---|---|---|
| New signal types | Requires editing the extractor | Add a field to the telemetry vector; extractor untouched |
| Per-consumer policy | Not expressible — one threshold for everyone | `TrustExecutionPolicy` is a parameter, not a constant |
| Auditability | A pass/fail log line, if anyone thought to add one | A full `TrustContract` record, hash-anchored, ledger-appended |
| Failure mode | Extractor either emits a record or silently drops it | `ACT`/`SUGGEST`/`HALT` — three distinct, observable outcomes |
| Implementation complexity | Low | Low-medium — one additional module (`trust.py`), no new infrastructure |

## Decision

Build the Trust Contract as a separate module (`bundesbrief.trust`) consuming an `ExtractionResult`'s telemetry, not as logic inside the extractor. `bundesbrief.extraction` never sees the confidence policy; `bundesbrief.trust` never parses raw text. The two compose through a plain dataclass boundary (`ExtractionResult`), which is also what keeps each independently unit-testable — see `tests/test_extraction.py` and `tests/test_trust.py`.

## Consequences

- **Positive**: the three confidence sub-scores (schema completeness, noise, freshness) are independently inspectable and independently weighted — a future tuning pass changes `trust.py`'s weights without touching extraction logic at all.
- **Positive**: the `TrustContract` is the natural unit to append to the hash-chained ledger (`bundesbrief.ledger`), giving Reconstruction (can we prove why a record was trusted) for free once Trust Contracts exist as real objects.
- **Negative, accepted for MVP scope**: the current telemetry vector is shallow — no cross-reference against the raw source image/page, no per-canton source-reliability history. Both are real future signals, not built here (see ROADMAP.md). The weights themselves (`0.5/0.3/0.2`) are a starting point, not calibrated against any real labeled dataset.
- **Negative, accepted for MVP scope**: this MVP operates on already-extracted plain text, not raw PDF bytes — real PDF layout parsing (pdfplumber/PyMuPDF against actual cantonal parliament PDFs) is deliberately out of scope here, to validate the trust-scoring architecture first rather than spend the available time on PDF parsing specifically.
