# Bundesbrief

**A confidence/truth layer over extracted Swiss parliamentary documents.** Built for the [openparla](https://luma.com/3avq28dg) open challenge, inspired by [OpenParlData.ch](https://gitlab.com/opendata.ch/openparldatach)'s unified-schema/API-first architecture.

Named for the 1291 Bundesbrief — the Federal Charter, the actual founding written document the Swiss Confederation's trust system is built on. The parallel is direct: a founding confederation needed a document whose authenticity everyone could independently verify. An automated pipeline extracting parliamentary affairs from inconsistent PDFs needs the same thing — not just a structured output, but a verifiable, machine-readable signal for *how much to trust it*.

**The problem:** PDF-extraction pipelines for Swiss parliamentary data (this one included, by default) have a view of the structured data they produce, but no insight into whether a given extraction was faithful to its source — a confident-looking record and a garbled one look identical once they're both just rows in a database. Bundesbrief wraps extraction in a **Trust Contract**: a per-record confidence score (schema completeness, OCR/parse noise, source staleness) that gates whether a record is auto-published (**Act**), flagged for human review (**Suggest**), or withheld entirely (**Halt**) — logged to an append-only, hash-chained ledger so every publish/withhold decision is independently verifiable after the fact. The gap is not hypothetical: in the recorded cross-check run over real Canton of Zurich PDFs, the regex extractor emitted an `affair_id` that the independent Apertus check flatly rejected as unsupported by the source text (agreement 0.0, flagging `affair_id` by name) — a cross-check disagreement found on real data, on the first small sample, which is exactly the failure mode a trust layer must surface.

## Quick start

```bash
make install
make test   # 100 unit tests: sample messy data, real generated PDFs (reportlab), MCP tools, cross-check (stub backend, offline)
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

Tools: `list_affairs`, `get_affair(affair_id)`, `verify_ledger`. `get_affair`'s output carries a `cross_check` block (agreement score, discrepancies, and a `backend` label that tells a measured Apertus agreement from a stub harness figure) — an agent client sees the cross-check signal, not just a human hitting `/docs`. Point an MCP client at
`python -m bundesbrief` — see [`config/claude_desktop_config.json.example`](config/claude_desktop_config.json.example)
and [`config/vscode_mcp_config.json.example`](config/vscode_mcp_config.json.example) for ready-made
client configs (copy, drop the `.example` suffix, fill in the path).

## Apertus cross-check (opt-in)

A fourth, independent signal: a locally served **quantised Apertus 8B** (a Q4_K_M GGUF quantisation
of `swiss-ai/Apertus-v1.5-8B`, Apache-2.0, pulled via `ollama pull
hf.co/Colby/apertus-v1.5-8b-text-Q4_K_M-GGUF:Q4_K_M`) re-reads the source text and judges how
strongly it supports each regex-extracted field. The deterministic pipeline stays authoritative:
the agreement dimension is active **only** when a real measurement was attached (weights rebalance
to `0.40/0.24/0.16/0.20`; otherwise today's `0.5/0.3/0.2` byte-for-byte), and a full disagreement
caps a record at Suggest — the model can veto auto-publication but never force a Halt alone
([ADR-003](docs/adrs/ADR-003%20%E2%80%94%20Apertus%20Cross-Check%20as%20a%20Conditional%20Fourth%20Dimension.md)).

```bash
make crosscheck        # stub backend: deterministic, offline, prints the STUB banner —
                       # harness-validation numbers, NOT submission numbers
BUNDESBRIEF_REAL_BACKENDS=1 make crosscheck-real   # the real run: 3 samples + a few real
                       # Canton of Zurich PDFs; records a JSON artifact under data/validation/
```

One environment variable (`BUNDESBRIEF_REAL_BACKENDS=1`, companions `BUNDESBRIEF_APERTUS_MODEL` /
`BUNDESBRIEF_APERTUS_HOST`) swaps stub for real — producing real numbers never requires a code
change. Every result carries its `backend` label, in the ledger, the REST endpoint
(`/affairs/{id}/cross-check`) and the MCP output alike, so a harness figure can never masquerade
as a measurement. Model failures are contained: the document still extracts, still scores, and the
record says plainly that the cross-check did not run and why. The local daemon setup, the exact
pull form that resolves, and the sizing rationale (2 CPU cores, ~6.8 GB free, no accelerator —
seconds-to-minutes per document) are in the `apertus_crosscheck` module docstring.

**Recorded real run** (2026-10-14, `data/validation/apertus-crosscheck-2026-10-14.json`): 3 sample
documents + 4 real Canton of Zurich PDFs — deliberately small, because measured per-document cost
on this box ran 4.5 s–85 s (a Q4_K_M 8B on 2 CPU cores, no accelerator; token spend per call is
recorded in the artifact). Execution location: **locally on the project workstation** — no cloud
virtual machine was created for the run (nor touched during setup), so there is no instance
identity or deletion evidence; the machine the artifact describes is the machine it ran on.
Result: agreement 1.0 on all three samples; 2 of 4 Zurich documents yielded no affair for
deterministic extraction at all (recorded, not cross-checked); and on both
Zurich documents that did yield fields, Apertus flatly rejected the regex-extracted `affair_id` as
unsupported by the source text (agreement 0.0) — the cross-check earning its keep on real data.

## What the three sample documents demonstrate

`data/sample_affairs/` ships three deliberately messy scenarios — not a cherry-picked clean dataset:

| File | Simulates | Trust mode | Apertus agreement* |
|---|---|---|---|
| `clean.txt` | A well-formed, recent document | **Act** — auto-published | 1.0 |
| `degraded_ocr.txt` | OCR corruption dropping some fields | **Suggest** — flagged for human review | 1.0 |
| `incomplete_stale.txt` | A 1998 document missing most fields entirely | **Halt** — withheld, logged, not published | 1.0 |

\* Real measurements from the locally served quantised Apertus 8B (recorded run `data/validation/apertus-crosscheck-2026-10-14.json`, stub-free, reproduced 2026-10-14). The agreement signal confirms all three extractions were faithful to their source text — corruption and staleness are what the *other* three signals carry, and the demo's point stands sharpened: three documents, **four independent signals**, three correct and different outcomes, and every agreement number labelled with the model tag that produced it.

This is the actual point of the project: the same pipeline, run against realistically messy input, makes three different, correct decisions instead of publishing all three with equal, unearned confidence.

## Architecture

```
raw PDF ──▶ extraction.py ──┐                       (PyMuPDF reads the
                            ├──▶ ExtractionResult   (fields found, noise with
clean text ─▶ (text path) ──┘                        named sub-scores))
                                        │
                                        ▼
        apertus_crosscheck.py ──▶ independent agreement signal (4th dimension,
             │                      active only when really measured — stub
             │                      by default, quantised Apertus 8B opt-in;
             │                      see docs/adrs/ADR-003)
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
- Confidence-score weights (`0.5` schema completeness / `0.3` noise / `0.2` freshness; `0.40/0.24/0.16/0.20` with a real Apertus measurement attached) are a starting point, not calibrated against any labeled dataset — see `ROADMAP.md` and ADR-003's falsifier for what would change them.
- **The Apertus cross-check talks to a model only when explicitly switched on.** The default is a deterministic substring-presence stub (which passes near-tautologically on the text path — it validates plumbing, not judgment, and deliberately never feeds the score); the measured numbers come from a community **Q4_K_M quantisation** served locally, not from the full `swiss-ai/Apertus-v1.5-8B` weights, and every artifact says which model tag answered. The recorded real run is small (3 samples + a handful of real Zurich documents) because 2 CPU cores make an 8B model seconds-to-minutes per document — the artifact carries the per-document timings that justify that size.
- The ledger is a local JSONL file, not a production-grade append-only store (no WORM backend, no distributed replication) — the guarantee it gives is "tampering is detectable," matching the smallest real version of the pattern, not a production deployment.
- No live connection to `api.openparldata.ch` or any real cantonal parliament source — see `ROADMAP.md`.

## Where the parts come from

The field-extraction design and the noise heuristic come from the author's sibling [`pdf-extract`](https://github.com/Willpower-hadisfar/pdf-extract) project (its pdfplumber engine was later swapped for PyMuPDF on the maintainer's cantonal-PDF benchmark — see ADR-002); confidence scoring delegates to the real [`trust-layer`](https://github.com/Willpower-hadisfar/trust-layer) package — **vendored verbatim** at `src/trust_layer/` because that repo is currently private and a forge-address dependency would break `make install` for anyone cloning this submission (judges included). Both are Apache 2.0, same author. Follow-up: de-vendor once upstream is public — tracked in `ROADMAP.md` and `src/trust_layer/VENDORED.md`.

## Naming note

"Bundesbrief" is this submission's name only. Unrelated to [Rütli](https://github.com/Powerworks-Global/ruetli) (a separate Hack Apertus submission by the same author) beyond both drawing on Apertus models and Swiss founding-history naming for the same reason: a resonant metaphor for mutual verification and trust, not a shared codebase or architecture. The Apertus role here is specific: an **independent cross-check signal** — a locally served quantised Apertus 8B scoring how strongly the source text supports each extracted field, as one weighted dimension of the Trust Contract — **not** the primary extraction engine, which stays deterministic regex + PyMuPDF parsing.

## License

Apache 2.0 — see [LICENSE](LICENSE).
