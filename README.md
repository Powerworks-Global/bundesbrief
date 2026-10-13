# Bundesbrief

**A confidence/truth layer over extracted Swiss parliamentary documents.** Built for the [openparla](https://luma.com/3avq28dg) open challenge, inspired by [OpenParlData.ch](https://gitlab.com/opendata.ch/openparldatach)'s unified-schema/API-first architecture.

Named for the 1291 Bundesbrief — the Federal Charter, the actual founding written document the Swiss Confederation's trust system is built on. The parallel is direct: a founding confederation needed a document whose authenticity everyone could independently verify. An automated pipeline extracting parliamentary affairs from inconsistent PDFs needs the same thing — not just a structured output, but a verifiable, machine-readable signal for *how much to trust it*.

**The problem:** PDF-extraction pipelines for Swiss parliamentary data (this one included, by default) have a view of the structured data they produce, but no insight into whether a given extraction was faithful to its source — a confident-looking record and a garbled one look identical once they're both just rows in a database. Bundesbrief wraps extraction in a **Trust Contract**: a per-record confidence score (schema completeness, OCR/parse noise, source staleness) that gates whether a record is auto-published (**Act**), flagged for human review (**Suggest**), or withheld entirely (**Halt**) — logged to an append-only, hash-chained ledger so every publish/withhold decision is independently verifiable after the fact.

## Quick start

```bash
make install
make test   # 45 unit tests: sample messy data, real generated PDFs (reportlab), MCP tools
make run    # starts the API on http://127.0.0.1:8000 — see /docs for Swagger UI
```

Then:
```bash
curl http://127.0.0.1:8000/affairs            # every sample affair + its trust mode
curl http://127.0.0.1:8000/affairs/GR-2026-0412  # full trust contract for one
curl http://127.0.0.1:8000/ledger/verify       # proves the justification ledger is untampered
```

## MCP server

The same pipeline is also exposed as an [MCP](https://modelcontextprotocol.io) server, so an
agent can pull a Trust Contract before deciding whether to act on a record, not just a human
hitting `/docs`.

```bash
make mcp    # runs the server over stdio — add it to an MCP client instead of running directly
```

Tools: `list_affairs`, `get_affair(affair_id)`, `verify_ledger`. Point an MCP client at
`python -m bundesbrief` — see [`config/claude_desktop_config.json.example`](config/claude_desktop_config.json.example)
and [`config/vscode_mcp_config.json.example`](config/vscode_mcp_config.json.example) for ready-made
client configs (copy, drop the `.example` suffix, fill in the path).

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
raw PDF ──▶ extraction.py ──┐                       (PyMuPDF reads the
                            ├──▶ ExtractionResult   (fields found, noise with
clean text ─▶ (text path) ──┘                        named sub-scores))
                                        │
                                        ▼
          trust.py ──▶ delegates scoring to the real `trust_layer` package
                        (noise registered inverted) ──▶ TrustContract
                                        │
                                        ▼
                                  ledger.py ──▶ append-only, hash-chained JSONL
                                        │
                                        ▼
                                   api.py ──▶ FastAPI, OpenAPI docs at /docs
                                   mcp_server.py ──▶ MCP tools over stdio (same contracts, agent-facing)
```

Each module is independently testable and doesn't know about the others' internals — see [`docs/adrs/ADR-001`](docs/adrs/ADR-001%20%E2%80%94%20Trust%20Contract%20as%20a%20Decoupled%20Layer%20over%20Extraction.md) for why extraction and trust-scoring are deliberately decoupled.

## Honest scope of this MVP

- **Real PDF extraction is in** (closed 2026-10-12, see [ADR-002](docs/adrs/ADR-002%20%E2%80%94%20Real%20PDF%20Extraction%20and%20a%20Vendored%20trust-layer%20Dependency.md)): `bundesbrief.extraction.extract_pdf` / `pipeline.process_pdf` read actual PDF bytes via **PyMuPDF** (~1.5 ms/page on 18 real Canton of Zurich documents) — the text layer, not OCR. A PDF with **no text layer at all** (a raw scan) yields empty text and no fields; genuine scans would need `pytesseract`/`pdf2image`, still out of scope. A malformed/unreadable PDF fails as a *recorded outcome* (`ExtractionResult.error`), never as an unhandled exception.
- The noise estimate is a **heuristic** of text-layer quality with named sub-scores (garbage ratio, lone-character ratio, replacement-character ratio, OCR-substitution ratio) — not a calibrated per-character OCR confidence, which text-layer readers like PyMuPDF don't expose because reading a text layer involves no OCR.
- Confidence-score weights (`0.5` schema completeness / `0.3` noise / `0.2` freshness) are a starting point, not calibrated against any labeled dataset.
- The ledger is a local JSONL file, not a production-grade append-only store (no WORM backend, no distributed replication) — the guarantee it gives is "tampering is detectable," matching the smallest real version of the pattern, not a production deployment.
- No live connection to `api.openparldata.ch` or any real cantonal parliament source — see `ROADMAP.md`.

## Where the parts come from

The field-extraction design and the noise heuristic come from the author's sibling [`pdf-extract`](https://github.com/Willpower-hadisfar/pdf-extract) project (its pdfplumber engine was later swapped for PyMuPDF on the maintainer's cantonal-PDF benchmark — see ADR-002); confidence scoring delegates to the real [`trust-layer`](https://github.com/Willpower-hadisfar/trust-layer) package — **vendored verbatim** at `src/trust_layer/` because that repo is currently private and a forge-address dependency would break `make install` for anyone cloning this submission (judges included). Both are Apache 2.0, same author. Follow-up: de-vendor once upstream is public — tracked in `ROADMAP.md` and `src/trust_layer/VENDORED.md`.

## Naming note

"Bundesbrief" is this submission's name only. Unrelated to [Rütli](https://github.com/Powerworks-Global/ruetli) (a separate Hack Apertus submission by the same author) beyond both using the Apertus model and both drawing on Swiss founding-history naming for the same reason: a resonant metaphor for mutual verification and trust, not a shared codebase or architecture.

## License

Apache 2.0 — see [LICENSE](LICENSE).
