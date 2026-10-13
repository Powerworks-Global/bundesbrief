# Roadmap

Time-ordered, Now/Next/Later — not a backlog. "Now" is this MVP, built to demonstrate the Trust Contract architecture against realistically messy data, not a finished product.

## Now (MVP, built 2026-10-11; MCP server added 2026-10-12)

- Trust Contract scoring (schema completeness, OCR/parse noise, source staleness) gating Act/Suggest/Halt.
- Hash-chained, append-only justification ledger with a `/ledger/verify` endpoint proving tamper-evidence.
- Three sample documents demonstrating all three outcomes on the same pipeline.
- FastAPI surface with free OpenAPI docs at `/docs`.
- MCP server (`mcp_server.py`, stdio transport) exposing `list_affairs`, `get_affair`, `verify_ledger` as
  tools — so an agent client checks `is_publication_permitted` before acting on a record, not just a
  human hitting `/docs`. Pattern modeled on [uk-parliament-data-mcp](https://github.com/ChrisBrooksbank/uk-parliament-data-mcp)
  (FastMCP, `register_tools(mcp)` per module, pipe-delimited discoverability docstrings).
- 45 unit tests (unittest, no pytest dependency — matches Rütli's convention), including real
  generated PDFs (reportlab) for the extraction path and the MCP tool tests.

## Next (if this gets real traction post-challenge)

- **MCP tool for submitting new text to score.** `mcp_server.py` currently only exposes the seeded
  sample-data pipeline (`list_affairs`/`get_affair`/`verify_ledger`). A `score_affair(raw_text,
  source_url, document_date)` tool wrapping `pipeline.process_document` directly would let an agent
  score arbitrary extracted text, not just replay the three samples — deferred rather than rushed,
  since it needs a decision on whether agent-submitted writes belong in the same ledger as the
  demo data or a separate one.
- **CLI.** uk-parliament-data-mcp ships a full Typer CLI (`parliament ...`) alongside its MCP server
  so the same tools are usable without an agent client. Worth considering once there's a reason to
  use Bundesbrief standalone, not just from an MCP host.
- ~~**Real PDF parsing.**~~ **Closed 2026-10-12:** real field extraction from PDF bytes via **PyMuPDF** (`extract_pdf`/`process_pdf`, ~1.5 ms/page on 18 real Canton of Zurich documents), with the named-sub-score noise heuristic and malformed-document containment. See [ADR-002](docs/adrs/ADR-002%20%E2%80%94%20Real%20PDF%20Extraction%20and%20a%20Vendored%20trust-layer%20Dependency.md). Still open underneath it: **raw scans need real OCR** (`pytesseract`/`pdf2image`) — text-layer PDFs only for now.
- **De-vendor `trust_layer`.** Replace the verbatim vendored copy at `src/trust_layer/` with a version-pinned public dependency once the upstream repo is public or on PyPI (currently private — a forge-address dependency would break `make install` for judges/strangers; see `src/trust_layer/VENDORED.md`). Same follow-up applies to `bundesbrief.ledger` → `trust_layer.ledger`: only viable as a forward-compatible format migration, never a silent re-hash of existing chains.
- **Calibrate the confidence weights against a labeled dataset.** The current `0.5/0.3/0.2` split is a reasonable starting point, not a tuned model — needs real extraction outcomes (correct vs. incorrect) to validate against.
- **Cross-reference signal.** Add a telemetry field scoring agreement between the extracted text and the raw source page image (e.g. a second-pass OCR confidence, or a vision-model cross-check) — the strongest signal this MVP doesn't yet have.
- **Per-source reliability history.** Track extraction success rate per canton/source over time and feed it back into the telemetry vector, the same way Rütli tracks policy-decision history — not built here, would need the ledger to accumulate real volume first.
- **Wire to a real source**, either `api.openparldata.ch` directly or a scraper against a specific canton's actual PDF publication feed.
- **A lightweight frontend** consuming `/affairs` — per the OpenParlData.ch inspiration note, kept decoupled from the processing pipeline, UI-only against the public API contract.

## Later (speculative)

- **Powerworks Consulting productization.** This exact pattern — a confidence/trust layer wrapping an existing extraction or data pipeline — maps directly onto the Truth Layer methodology already written up for Powerworks Consulting's AI governance audit practice. Worth a deliberate look once this has a real result to point to, not something to start building now.
- **Revisit the Rütli ledger's hardening measures** (WORM mirror, crypto-shredding for GDPR/FADP erasure) if this ledger ever needs to hold real personal data rather than public parliamentary records, which generally don't carry the same erasure obligations.

## What this roadmap deliberately leaves out

No committed dates. This was built to demonstrate an architecture, not shipped as a product — "Next" and "Later" are directions worth pursuing if there's a real reason to (challenge feedback, a client conversation), not a schedule.
