# Bundesbrief

**A confidence/truth layer over extracted Swiss parliamentary documents.** Built for the [openparla](https://luma.com/3avq28dg) open challenge, inspired by [OpenParlData.ch](https://gitlab.com/opendata.ch/openparldatach)'s unified-schema/API-first architecture.

Named for the 1291 Bundesbrief — the Federal Charter, the actual founding written document the Swiss Confederation's trust system is built on. The parallel is direct: a founding confederation needed a document whose authenticity everyone could independently verify. An automated pipeline extracting parliamentary affairs from inconsistent PDFs needs the same thing — not just a structured output, but a verifiable, machine-readable signal for *how much to trust it*.

**The problem:** PDF-extraction pipelines for Swiss parliamentary data (this one included, by default) have a view of the structured data they produce, but no insight into whether a given extraction was faithful to its source — a confident-looking record and a garbled one look identical once they're both just rows in a database. Bundesbrief wraps extraction in a **Trust Contract**: a per-record confidence score (schema completeness, OCR/parse noise, source staleness) that gates whether a record is auto-published (**Act**), flagged for human review (**Suggest**), or withheld entirely (**Halt**) — logged to an append-only, hash-chained ledger so every publish/withhold decision is independently verifiable after the fact.

## Quick start

```bash
make install
make test   # 15 unit tests, run against sample messy data
make run    # starts the API on http://127.0.0.1:8000 — see /docs for Swagger UI
```

Then:
```bash
curl http://127.0.0.1:8000/affairs            # every sample affair + its trust mode
curl http://127.0.0.1:8000/affairs/GR-2026-0412  # full trust contract for one
curl http://127.0.0.1:8000/ledger/verify       # proves the justification ledger is untampered
```

## What the three sample documents demonstrate

`data/sample_affairs/` ships three deliberately messy scenarios — not a cherry-picked clean dataset:

| File | Simulates | Trust mode |
|---|---|---|
| `clean.txt` | A well-formed, recent document | **Act** — auto-published |
| `degraded_ocr.txt` | OCR corruption dropping some fields | **Suggest** — flagged for human review |
| `incomplete_stale.txt` | A 1998 document missing most fields entirely | **Halt** — withheld, logged, not published |

This is the actual point of the project: the same pipeline, run against realistically messy input, makes three different, correct decisions instead of publishing all three with equal, unearned confidence.

## Architecture

```
raw text ──▶ extraction.py ──▶ ExtractionResult (fields found, noise ratio)
                                        │
                                        ▼
                                  trust.py ──▶ TrustContract (confidence score, Act/Suggest/Halt)
                                        │
                                        ▼
                                  ledger.py ──▶ append-only, hash-chained JSONL
                                        │
                                        ▼
                                   api.py ──▶ FastAPI, OpenAPI docs at /docs
```

Each module is independently testable and doesn't know about the others' internals — see [`docs/adrs/ADR-001`](docs/adrs/ADR-001%20%E2%80%94%20Trust%20Contract%20as%20a%20Decoupled%20Layer%20over%20Extraction.md) for why extraction and trust-scoring are deliberately decoupled.

## Honest scope of this MVP

- Operates on **already-extracted plain text**, not raw PDF bytes — real PDF layout parsing (pdfplumber/PyMuPDF against actual cantonal parliament PDFs) is the next real step, not built here. The point of this pass was validating the trust-scoring architecture first.
- Confidence-score weights (`0.5` schema completeness / `0.3` noise / `0.2` freshness) are a starting point, not calibrated against any labeled dataset.
- The ledger is a local JSONL file, not a production-grade append-only store (no WORM backend, no distributed replication) — the guarantee it gives is "tampering is detectable," matching the smallest real version of the pattern, not a production deployment.
- No live connection to `api.openparldata.ch` or any real cantonal parliament source — see `ROADMAP.md`.

## Naming note

"Bundesbrief" is this submission's name only. Unrelated to [Rütli](https://github.com/Powerworks-Global/ruetli) (a separate Hack Apertus submission by the same author) beyond both using the Apertus model and both drawing on Swiss founding-history naming for the same reason: a resonant metaphor for mutual verification and trust, not a shared codebase or architecture.

## License

Apache 2.0 — see [LICENSE](LICENSE).
