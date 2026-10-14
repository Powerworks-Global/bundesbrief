# ADR-003: Apertus Cross-Check as a Conditional Fourth Dimension, Not an Extraction Replacement

**Status:** Accepted
**Date:** 2026-10-14
**Deciders:** William Power
**Project:** Bundesbrief (openparla challenge — Track 2A "Academia Challenge", HackApertus)

---

## Context

ADR-001 accepted, as an explicit MVP limitation, that "the current telemetry vector is shallow — no cross-reference against the raw source page." ROADMAP.md called that signal the strongest one the MVP didn't yet have. This ADR records adding it: an Apertus cross-check that independently judges how strongly the raw source text supports the regex extractor's field values.

Four constraints made this harder than "add a field":

1. **The ledger's hash chain.** `bundesbrief.ledger` hashes `TrustContract.model_dump_json() + previous_hash`; ADR-002 reproduced the landmine — one added optional field retroactively broke a 900-entry chain. Any new telemetry dimension must leave every pre-existing record re-hashing byte-identically.
2. **Deterministic authority.** The pipeline must stay fully auditable with no model in the loop, offline, and never required; a caller asking for the trust verdict without a cross-check must get the same number the code produces today.
3. **First model call, judged entry.** This repository previously made zero LLM calls. Numbers must be honestly attributed: a locally-served **community Q4_K_M quantisation** of `swiss-ai/Apertus-v1.5-8B` (repo `Colby/apertus-v1.5-8b-text-Q4_K_M-GGUF`; verified not gated, Apache-2.0, single GGUF) through a local Ollama daemon — no hosted endpoint, no credential. Plain `ollama pull <repo>` fails here ("pull model manifest: file does not exist"); `ollama pull hf.co/Colby/apertus-v1.5-8b-text-Q4_K_M-GGUF:Q4_K_M` resolves. Numbers come from the quantised weights, never described as the full upstream ones.
4. **Honest stub.** CI can't depend on a model; the sibling project's convention separates deterministic stub-backend tests from an opt-in real-backend run whose output is *recorded*, not asserted. A stub figure must be unmaskable as a measurement.

## Considered Options

| Evaluation Metric | Model replaces extraction | Sidecar score (contract untouched) | Conditional 4th dimension (Chosen) |
|---|---|---|---|
| Solves the missing signal | Yes, at the root | Yes | Yes |
| Deterministic auditability without model | Lost — model in the critical path | Kept | Kept — model absent ⇒ today's exact path |
| Ledger wire-format impact | Total re-hash | None | None for pre-existing records (measured-if-present serialization, verified below) |
| Signal can arbitrate the pipeline | No — it *is* the pipeline | Yes, but only to humans reading two artifacts | Yes — disagreement can veto ACT inside the contract |
| Existing 45 tests | Rewritten | Untouched | Untouched |

## Decision

1. **`bundesbrief.apertus_crosscheck`** adds a `CrossCheckResult(agreement_score, discrepancies, backend, provenance)` — `backend` names *what produced the number* (`ollama:<model tag>` / `stub:…` / `not-run:…`), the honesty mechanism at the data layer; a stub score is distinguishable from a measured one from the record alone, through the REST endpoint, the MCP `get_affair` `cross_check` block, and every ledger entry. `StubApertusCrossCheck` (default, used by every test) is a deterministic literal-presence heuristic — explicitly **not** a simulation of the model's judgment. `OllamaApertusCrossCheck` talks to the daemon's `/api/generate` in JSON mode; reply parsing is a trust boundary: malformed JSON, missing keys, out-of-range score, or non-list `discrepancies` raise naming what came back — never a defaulted score. One env var swaps backends (`BUNDESBRIEF_REAL_BACKENDS=1`, companion vars for model/host); every run prints a banner naming the backend, the stub banner stating its numbers are harness-validation figures only.
2. **Weights rebalance only when a real measurement is attached:** completeness/noise/freshness keep their exact internal ratio, rescaled to share 0.8 — `0.40/0.24/0.16` — and `apertus_agreement` gets `0.20`. Unmeasured, stub, and not-run records score the original `0.5/0.3/0.2`, byte-for-byte today's numbers. The 0.2/0.8 split keeps the deterministic trio authoritative while giving one 8B-model opinion real consequence: agreement 0.0 caps a deterministically perfect record at 0.8 — below ACT, so full disagreement forces Suggest review — without a model alone ever forcing HALT. **Falsifier:** on a labelled corpus, if agreement's error-discrimination is no better than noise's, 0.2 is over-weighted and should collapse into the trio; if records the model rejects but the trio accepts dominate the false-publish cases, 0.2 is under-weighted. Until such a corpus exists (ROADMAP's calibration bullet), the split stays reasoned, not tuned.
3. **Ledger integrity by absence-if-unmeasured:** `TrustTelemetryVector.apertus_agreement_score` defaults to a neutral 1.0 ("not penalised", never "verified"), but its serializer — and thus the hash payload, `to_dict`, and `verify()` — omits all three `apertus_*` keys whenever `apertus_backend is None`. Verified empirically, not reasoned: the repository's real pre-existing `ledger.jsonl`/`mcp_ledger.jsonl`, and a 300-entry chain built with the pre-change code, all verify `True` under the new code; unmeasured telemetry dumps byte-identical to its pre-change JSON; a pinned pre-change fixture chain is a test; forging `apertus` keys into a stored legacy entry breaks verification.
4. **Wired into the real path** (`process_document`/`process_pdf`, default `cross_check="auto"`): a model failure — unreachable daemon, timeout, unparseable reply — never fails a document; the record carries `not-run: <reason>`, scores deterministically, and the suite pins this containment.

## Consequences

- **Positive:** the demo now tells a four-signal story (three deterministic + agreement) across three correct, different outcomes; an MCP agent sees the cross-check and its provenance without leaving `get_affair`, whose tool surface stays three tools.
- **Positive:** real-backend numbers arrive via one documented command (`BUNDESBRIEF_REAL_BACKENDS=1 make crosscheck-real`) on a 2-core/~6.8 GB box — small by necessity (3 samples + a handful of real Zurich pages), with per-document timings and token provenance recorded in the artifact so the size is justified by measurement, and the recorded run reproducible from docstrings alone.
- **Negative, accepted:** a stub label passes near-tautologically on the text path (regex values are substrings of the source); it is plumbing validation, deliberately kept out of the authoritative score.
- **Negative, accepted:** the fourth dimension is only as good as a quantised 8B judge on a CPU box — seconds-to-minutes per document — which is exactly why it advises rather than extracts, at weight 0.2.
