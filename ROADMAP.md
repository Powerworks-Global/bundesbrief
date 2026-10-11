# Roadmap

Time-ordered, Now/Next/Later — not a backlog. "Now" is this MVP, built to demonstrate the Trust Contract architecture against realistically messy data, not a finished product.

## Now (MVP, built 2026-10-11)

- Trust Contract scoring (schema completeness, OCR/parse noise, source staleness) gating Act/Suggest/Halt.
- Hash-chained, append-only justification ledger with a `/ledger/verify` endpoint proving tamper-evidence.
- Three sample documents demonstrating all three outcomes on the same pipeline.
- FastAPI surface with free OpenAPI docs at `/docs`.
- 15 unit tests (unittest, no pytest dependency — matches Rütli's convention).

## Next (if this gets real traction post-challenge)

- **Real PDF parsing.** Swap the plain-text extraction stub for pdfplumber/PyMuPDF against actual cantonal parliament PDFs. This is the single biggest gap between "architecture demo" and "actually solves openparla's brief."
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
