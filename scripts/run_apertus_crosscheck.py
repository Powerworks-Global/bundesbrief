#!/usr/bin/env python3
"""
The documented, opt-in REAL-BACKEND cross-check run — the one command that
produces submission numbers (Rütli's convention: stub tests in CI, a real
validation run whose output is RECORDED, not asserted).

What it does
------------
1. Prints the backend banner (names the model in play — or, if the switch
   is off, states plainly that the numbers are harness-validation figures;
   see bundesbrief.apertus_crosscheck).
2. Runs the cross-check over the three sample documents, plus a small
   handful of REAL Canton of Zurich PDFs fetched through
   api.openparldata.ch -> notes.zh.ch (the same source chain ADR-002's
   benchmark used).
3. Records every number, per-document timing, and token provenance to a
   JSON artifact. Nothing is asserted here; the artifact is the point.

Sizing, honestly: this box has 2 CPU cores, ~6.8 GB free memory and no
accelerator, and the model is a Q4_K_M quantisation of an 8B model
(quantised Apertus of `swiss-ai/Apertus-v1.5-8B`; local weights, not the
full upstream ones). Generation runs seconds-to-minutes per document, so
the real run is deliberately small: 3 samples + a few Zurich documents —
enough to be a genuine measurement, small enough to actually finish. The
recorded artifact carries the per-document timings that justify the size.

Usage (setup details also in src/bundesbrief/apertus_crosscheck.py):

    OLLAMA_MODELS=/tmp/ollama-models ~/.local/bin/ollama serve &
    ~/.local/bin/ollama pull hf.co/Colby/apertus-v1.5-8b-text-Q4_K_M-GGUF:Q4_K_M
    BUNDESBRIEF_REAL_BACKENDS=1 make crosscheck-real

Options:
    --zh N          number of real Zurich documents (default 4; 0 skips)
    --out PATH      artifact path (default data/validation/apertus-crosscheck-<UTC date>.json)
    --allow-stub    proceed with the stub backend (harness validation only —
                    the artifact will say so, loudly, per record)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from bundesbrief.apertus_crosscheck import (  # noqa: E402
    DEFAULT_MODEL,
    MODEL_ENV,
    CrossCheckError,
    get_crosscheck_backend,
    log_backend,
    real_backends_enabled,
)
from bundesbrief.extraction import extract_pdf  # noqa: E402
from bundesbrief.pipeline import process_sample_data_outcomes  # noqa: E402
from bundesbrief.ledger import Ledger  # noqa: E402
from bundesbrief.trust import build_trust_contract, compute_confidence  # noqa: E402
from bundesbrief.models import TrustTelemetryVector  # noqa: E402

API_BASE = "https://api.openparldata.ch/v1"
CACHE_DIR = Path("/tmp/bundesbrief_zh_pdfs")


def _get_json(url: str, timeout: int = 60):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_zh_pdfs(count: int) -> list[dict]:
    """Up to `count` real Canton of Zurich PDFs: affairs -> /docs -> notes.zh.ch bytes.

    Downloads are cached under /tmp so re-runs don't refetch. Each entry:
    {path, affair_number, title, doc_url}.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    collected: list[dict] = []
    offset = 0
    while len(collected) < count and offset < 400:
        page = _get_json(f"{API_BASE}/affairs/?body_key=ZH&offset={offset}&limit=25")
        offset += 25
        for affair in page.get("data", []):
            if len(collected) >= count:
                break
            number = affair.get("number") or str(affair["id"])
            title = (affair.get("title") or {}).get("de", "")
            try:
                docs = _get_json(f"{API_BASE}/affairs/{affair['id']}/docs").get("data", [])
            except Exception as exc:  # noqa: BLE001 - source hiccup: skip this affair
                print(f"  [zh] docs lookup failed for {number}: {exc}", file=sys.stderr)
                continue
            for doc in docs:
                url = doc.get("url", "")
                if not url.lower().endswith(".pdf"):
                    continue
                size = doc.get("size") or 0
                if size and size > 4_000_000:  # keep the tiny box's run bounded
                    continue
                safe = "".join(c if c.isalnum() else "_" for c in number)[:40]
                path = CACHE_DIR / f"{safe}.pdf"
                if not path.exists():
                    try:
                        # notes.zh.ch serves unencoded umlauts in paths;
                        # percent-encode while preserving existing %XX escapes.
                        fetch_url = urllib.parse.quote(url, safe=":/?=&%#")
                        with urllib.request.urlopen(fetch_url, timeout=120) as resp:
                            path.write_bytes(resp.read())
                    except Exception as exc:  # noqa: BLE001
                        print(f"  [zh] download failed for {number}: {exc}", file=sys.stderr)
                        continue
                collected.append(
                    {"path": str(path), "affair_number": number, "title": title, "doc_url": url}
                )
                break
    return collected[:count]


def cross_check_one(backend, affair, source_text: str) -> tuple[dict, object | None]:
    """One timed cross-check call; failures recorded, never raised away.

    Returns (JSON-ready payload, CrossCheckResult-or-None).
    """
    started = time.monotonic()
    try:
        result = backend.compare(affair, source_text)
    except CrossCheckError as exc:
        return {"error": str(exc), "elapsed_ms": round((time.monotonic() - started) * 1000, 1)}, None
    except Exception as exc:  # noqa: BLE001
        return {
            "error": f"unexpected {type(exc).__name__}: {exc}",
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        }, None
    payload = result.as_dict()
    payload["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
    return payload, result


def deterministic_confidence(contract) -> float:
    """The contract's score on its deterministic dimensions alone."""
    t: TrustTelemetryVector = contract.telemetry
    return compute_confidence(
        TrustTelemetryVector(
            fields_expected=t.fields_expected,
            fields_found=t.fields_found,
            ocr_noise_ratio=t.ocr_noise_ratio,
            source_age_days=t.source_age_days,
            max_acceptable_age_days=t.max_acceptable_age_days,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("Usage")[0])
    parser.add_argument("--zh", type=int, default=4, help="real Zurich documents to cross-check (0 to skip)")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--allow-stub", action="store_true")
    args = parser.parse_args()

    if not real_backends_enabled() and not args.allow_stub:
        print(
            "Refusing to present this as the real run: BUNDESBRIEF_REAL_BACKENDS is not\n"
            "set to 1, so the stub backend would produce harness-validation figures only.\n"
            "For the real run: BUNDESBRIEF_REAL_BACKENDS=1 make crosscheck-real\n"
            "(setup: src/bundesbrief/apertus_crosscheck.py docstring).\n"
            "For a harness run anyway: add --allow-stub.",
            file=sys.stderr,
        )
        return 2

    backend = get_crosscheck_backend()
    log_backend(backend)

    out_path = args.out or REPO_ROOT / "data" / "validation" / (
        f"apertus-crosscheck-{datetime.now(timezone.utc):%Y-%m-%d}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    artifact: dict = {
        "kind": "bundesbrief-apertus-crosscheck-run",
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "backend_kind": "real-model" if real_backends_enabled() else "stub-harness-validation",
        "backend_label": backend.backend,
        "model_note": (
            "Upstream model: swiss-ai/Apertus-v1.5-8B. Weights actually run: community "
            "Q4_K_M GGUF quantisation served locally via Ollama "
            f"({os.environ.get(MODEL_ENV) or DEFAULT_MODEL}). Numbers are from the "
            "quantised local weights, not the full upstream weights."
        )
        if real_backends_enabled()
        else "STUB RUN - harness validation figures only, no model involved.",
        "hardware_note": "2 CPU cores, ~6.8 GB free memory, no accelerator; run sized to 3 samples + a few real Zurich documents",
        "documents": [],
    }

    print(":: sample documents", file=sys.stderr)
    ledger_path = Path("/tmp/bundesbrief_crosscheck_ledger.jsonl")
    ledger_path.unlink(missing_ok=True)
    for outcome in process_sample_data_outcomes(
        REPO_ROOT / "data" / "sample_affairs", ledger_path, cross_check=None
    ):
        cc, cc_result = cross_check_one(backend, outcome.affair, outcome.source_text)
        artifact["documents"].append(
            {
                "kind": "sample",
                "affair_id": outcome.contract.affair_id,
                "deterministic_confidence": deterministic_confidence(outcome.contract),
                "deterministic_mode": outcome.contract.current_mode.value,
                "cross_check": cc,
            }
        )
        print(f"   {artifact['documents'][-1]}", file=sys.stderr)

    if args.zh > 0:
        print(f":: {args.zh} real Canton of Zurich documents", file=sys.stderr)
        for doc in fetch_zh_pdfs(args.zh):
            entry: dict = {"kind": "zurich", "affair_number": doc["affair_number"], "title": doc["title"], "doc_url": doc["doc_url"]}
            started = time.monotonic()
            result = extract_pdf(doc["path"], source_url=doc["doc_url"])
            entry["extract_ms"] = round((time.monotonic() - started) * 1000, 1)
            if result.error is not None or result.affair is None:
                entry["note"] = result.error or "no affair_id found by deterministic extraction - nothing to cross-check"
                entry["fields_found"] = result.fields_found
                artifact["documents"].append(entry)
                print(f"   {entry}", file=sys.stderr)
                continue
            cc, cc_result = cross_check_one(backend, result.affair, result.source_text)
            entry["fields_found"] = result.fields_found
            entry["fields_expected"] = result.fields_expected
            entry["ocr_noise_ratio"] = result.ocr_noise_ratio
            entry["cross_check"] = cc
            # What the contract WOULD look like with the measurement attached,
            # scored against a neutral age (publication dates vary; freshness
            # is orthogonal to what this run measures):
            contract = build_trust_contract(
                result.affair, result, source_age_days=0.0,
                cross_check=cc_result,
                cross_check_failure=cc.get("error"),
            )
            entry["confidence_3dim_deterministic_only"] = deterministic_confidence(contract)
            entry["confidence_with_cross_check"] = contract.confidence_score
            entry["mode"] = contract.current_mode.value
            artifact["documents"].append(entry)
            print(f"   {entry}", file=sys.stderr)

    out_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nRecorded run artifact -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
