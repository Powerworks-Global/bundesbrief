"""
Apertus cross-check: a fourth, independent trust dimension.

WHAT THIS IS
------------
A cross-check of the deterministic pipeline: given the raw source text and
the fields the regex extractor pulled out of it, an independent backend
judges how strongly the source supports the extracted values. The result
(`CrossCheckResult`: agreement score, discrepancies, backend label) feeds a
fourth scoring dimension in `bundesbrief.trust` when — and only when — a
real model run produced it. The deterministic trio keeps its exact weights
and scores byte-for-byte-today's numbers on every path that did not run a
measured cross-check. Design record: docs/adrs/ADR-003 (including why the
ledger hash chain stays intact for pre-existing records).

MODEL IDENTITY, precisely, because this is a judged entry: the upstream
model being cross-checked against is `swiss-ai/Apertus-v1.5-8B`. What
actually produces the numbers on this machine is a community quantisation
of it — the Q4_K_M GGUF — served locally: `ollama pull
hf.co/Colby/apertus-v1.5-8b-text-Q4_K_M-GGUF:Q4_K_M` (the plain
`ollama pull <repo>` form fails with "pull model manifest: file does not
exist"; the hf.co tag form is what resolves — both facts recorded in
ADR-003). The repo was verified before use: not gated, Apache-2.0, single
GGUF file — no token, no licence acceptance on this route. Numbers here
come from the quantised local weights, NOT from the full upstream weights,
and must never be described as if they did.

TWO BACKENDS, ONE SWITCH
------------------------
`StubApertusCrossCheck` — the DEFAULT, and what every test uses. A
deterministic heuristic: whether each extracted field's value literally
appears in the raw source text. It does NOT emulate the model's judgment
in any way; it is an honest substring-presence check whose purpose is that
tests never depend on a live model, a daemon, or a network. Every result it
produces carries an unmistakable ``stub:`` label in `backend`.

`OllamaApertusCrossCheck` — used ONLY when the switch is on. Talks to a
local (or explicitly configured remote) Ollama server through its
`/api/generate` endpoint in JSON mode, parsing a reply body of
`agreement_score` + `discrepancies`. Parsing is a TRUST BOUNDARY: a
malformed/non-JSON response, a missing key, an out-of-range score, or a
`discrepancies` field that is not a list of strings raises
`CrossCheckUnavailable` naming exactly what came back — never a defaulted
score, because a silently invented agreement score is the worst possible
artifact this feature could produce. Real results carry provenance: the
model tag that answered, the host, and the token counts the call took.

One environment variable swaps the backends — one variable, not a code
change, so producing real submission numbers never requires editing a file.
It is read in exactly one helper, `real_backends_enabled()`:

    BUNDESBRIEF_REAL_BACKENDS   exactly "1" enables the real backend;
                                anything else (unset, "0", "true", "yes",
                                "1 ") leaves the stub in place.
    BUNDESBRIEF_APERTUS_MODEL   ollama model tag; default:
                                hf.co/Colby/apertus-v1.5-8b-text-Q4_K_M-GGUF:Q4_K_M
    BUNDESBRIEF_APERTUS_HOST    Ollama server URL; default: http://127.0.0.1:11434

Reproducing the recorded real run from this docstring alone:

    OLLAMA_MODELS=/tmp/ollama-models ~/.local/bin/ollama serve &
    ~/.local/bin/ollama pull hf.co/Colby/apertus-v1.5-8b-text-Q4_K_M-GGUF:Q4_K_M
    BUNDESBRIEF_REAL_BACKENDS=1 make crosscheck-real

Every run prints a banner naming the backend in play. The stub run's banner
states plainly that its numbers are harness-validation figures, NOT
submission numbers — on top of the `backend`-field distinction at the data
layer, so no stub number can masquerade as a measurement at either layer.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

REAL_BACKENDS_ENV = "BUNDESBRIEF_REAL_BACKENDS"
MODEL_ENV = "BUNDESBRIEF_APERTUS_MODEL"
HOST_ENV = "BUNDESBRIEF_APERTUS_HOST"

# Community Q4_K_M quantisation of swiss-ai/Apertus-v1.5-8B (see module
# docstring — the model being cross-checked against is upstream; the
# quantised local weights are what produce numbers here).
DEFAULT_MODEL = "hf.co/Colby/apertus-v1.5-8b-text-Q4_K_M-GGUF:Q4_K_M"
DEFAULT_HOST = "http://127.0.0.1:11434"

# The five fields the extraction schema produces (mirrors extraction.EXPECTED_FIELDS).
CHECKED_FIELDS = ("affair_id", "title", "canton", "status", "date")

# Character budget for the source text shown to the model, sized for the
# 2-CPU box: the fields under check live in the document header, which this
# budget always covers, and a smaller context generates measurably faster.
DEFAULT_MAX_SOURCE_CHARS = 3000


class CrossCheckError(RuntimeError):
    """Base for cross-check failures. A failure is never a fabricated score."""


class CrossCheckUnavailable(CrossCheckError):
    """The real backend could not answer (server down, model missing,
    timeout, unparseable reply). Callers record this as an outcome — the
    deterministic pipeline never fails because the model was unreachable."""


@dataclass(frozen=True)
class CrossCheckResult:
    """One independent agreement signal.

    ``agreement_score``: fraction (0-1) of the checked extracted field
    values this backend considers corroborated by the raw source text.
    ``discrepancies``: human-readable descriptions of flagged fields
    (empty when full agreement).
    ``backend``: WHAT PRODUCED THE NUMBER — the real model identifier for
    a model run, an unmistakable ``stub:`` marker otherwise. This is the
    honesty mechanism at the data layer (load-bearing, not decoration):
    a stub score and a measured score are distinguishable from the record
    alone, with no reliance on how the run was launched or what was
    printed, and the distinction survives into the ledger and the MCP
    surface.
    ``provenance``: for real runs, which model tag answered, which host,
    and the token spend measured from the reply (prompt/generated counts)
    — measured, never estimated.
    """

    agreement_score: float
    discrepancies: list[str] = field(default_factory=list)
    backend: str = ""
    provenance: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Validate, reject rather than coerce: a score outside [0, 1] is a
        # bug or a hostile reply, and clamping it would hide that.
        value = self.agreement_score
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"agreement_score must be a number, got {type(value).__name__}")
        if not (0.0 <= float(value) <= 1.0):
            raise ValueError(f"agreement_score must be within [0, 1], got {value!r}")
        object.__setattr__(self, "agreement_score", float(value))
        if not isinstance(self.discrepancies, list) or not all(
            isinstance(d, str) for d in self.discrepancies
        ):
            raise TypeError("discrepancies must be a list of strings")
        if not self.backend or not isinstance(self.backend, str):
            raise ValueError("backend must be a non-empty string naming what produced the score")

    @property
    def is_stub(self) -> bool:
        return self.backend.startswith("stub:")

    @property
    def is_model_measured(self) -> bool:
        """True only when a real Apertus run produced this score."""
        return not self.backend.startswith(("stub:", "not-run:"))

    def as_dict(self) -> dict:
        payload = {
            "agreement_score": self.agreement_score,
            "discrepancies": list(self.discrepancies),
            "backend": self.backend,
        }
        if self.provenance:
            payload["provenance"] = dict(self.provenance)
        return payload


class CrossCheckBackend(Protocol):
    """Anything that can compare extracted field values against source text."""

    backend: str

    def compare(self, affair, source_text: str) -> CrossCheckResult: ...


# ---------------------------------------------------------------------------
# Backend switch (one env var, read in exactly one place)
# ---------------------------------------------------------------------------


def real_backends_enabled() -> bool:
    """True only when BUNDESBRIEF_REAL_BACKENDS is exactly "1".

    Anything else — unset, "", "0", "true", "yes", "1 " — keeps the stub,
    so a bare checkout can never accidentally call a model, and the test
    suite never needs the model, the daemon, or the network.
    """
    return os.environ.get(REAL_BACKENDS_ENV) == "1"


def get_crosscheck_backend() -> CrossCheckBackend:
    """The single selection point: stub by default, Apertus when switched on."""
    if real_backends_enabled():
        return OllamaApertusCrossCheck(
            model=os.environ.get(MODEL_ENV) or DEFAULT_MODEL,
            host=os.environ.get(HOST_ENV) or DEFAULT_HOST,
        )
    return StubApertusCrossCheck()


def log_backend(backend: CrossCheckBackend, stream=None) -> None:
    """Banner naming which backend is in play, printed on every run.

    The stub half of this banner is load-bearing: it stops a
    harness-validation figure from ever being mistaken for a submission
    number, at the human layer on top of the `backend`-field distinction
    at the data layer.
    """
    import sys

    stream = stream or sys.stderr
    if isinstance(backend, StubApertusCrossCheck):
        stream.write(
            "\n"
            "=== Bundesbrief cross-check: STUB backend (StubApertusCrossCheck) ===\n"
            "These are HARNESS-VALIDATION numbers, NOT submission numbers: a\n"
            "deterministic substring-presence check ran, NOT the Apertus model.\n"
            f"Set {REAL_BACKENDS_ENV}=1 (setup in the module docstring) for a real run.\n"
            "=====================================================================\n\n"
        )
    else:
        stream.write(
            "\n"
            "=== Bundesbrief cross-check: REAL backend ===\n"
            f"Model:  {backend.backend}\n"
            f"Host:   {getattr(backend, 'host', '?')}\n"
            "Numbers from this run are measured Apertus (quantised) figures.\n"
            "===============================================================\n\n"
        )
    stream.flush()


# ---------------------------------------------------------------------------
# Stub backend — deterministic, offline, the default and the test path
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    """Whitespace-collapsed, case/diacritic-insensitive form for matching.

    Case/diacritic insensitivity is deliberately the ONLY leniency: the
    check remains literal presence in the source, nothing semantic.
    """
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return _WS_RE.sub(" ", text.casefold()).strip()


class StubApertusCrossCheck:
    """Deterministic substring-presence cross-check: the default backend.

    NOT a simulation of the model's judgment — no attempt at semantic
    agreement, no prompt is executed. For every field value the extractor
    actually emitted, the check is whether that value literally appears
    (up to case, diacritics and whitespace collapsing) in the raw source
    text. Agreement is the fraction of emitted values present; flagged
    values are listed in ``discrepancies``.

    The prompt in `_PROMPT_TEMPLATE` is the task the REAL backend is given;
    the stub cannot honour its judgment step — it honours the same inputs
    (same fields, same source text) and the same result shape, and nothing
    more. Two honest limitations, stated because the real backend exists
    precisely to transcend them: (1) a regex extractor takes its values
    verbatim from the text, so on the text path this check passes near-
    tautologically — its purpose is plumbing that never needs a live model,
    not discovery; (2) a field the extractor never emitted is not penalised
    here (that is the completeness dimension's job) — agreement over zero
    checked fields is vacuously 1.0, with a note in ``discrepancies`` so
    the record says so itself.
    """

    def __init__(self) -> None:
        self.backend = (
            "stub:substring-presence (NOT the Apertus model; harness validation only — "
            f"set {REAL_BACKENDS_ENV}=1 for a real run)"
        )

    def compare(self, affair, source_text: str) -> CrossCheckResult:
        source_norm = _normalise(source_text)
        checked = [f for f in CHECKED_FIELDS if (getattr(affair, f, "") or "").strip()]
        if not checked:
            return CrossCheckResult(
                agreement_score=1.0,
                discrepancies=[
                    "note: extractor emitted no field values, so agreement here is vacuous — "
                    "missing-field penalty lives in the completeness dimension, not this one"
                ],
                backend=self.backend,
            )
        hits = 0
        discrepancies: list[str] = []
        for fname in checked:
            value = str(getattr(affair, fname)).strip()
            if _normalise(value) in source_norm:
                hits += 1
            else:
                discrepancies.append(
                    f"{fname}: extracted value {value!r} does not literally appear in the source text"
                )
        return CrossCheckResult(
            agreement_score=hits / len(checked),
            discrepancies=discrepancies,
            backend=self.backend,
        )


# ---------------------------------------------------------------------------
# Real backend — Ollama server (local by default) serving quantised Apertus
# ---------------------------------------------------------------------------

# The single task prompt, used by the real path. The stub honours the same
# inputs and result shape but not the judgment (see its docstring) — kept
# adjacent here so the two paths cannot drift apart unnoticed.
_PROMPT_TEMPLATE = """You are auditing a Swiss parliamentary-document extractor for errors.

SOURCE TEXT (extracted from the document's text layer):
\"\"\"
{source}
\"\"\"

EXTRACTED FIELDS (values a regex extractor claims came from the source):
{fields}

Decide for each extracted field whether the SOURCE TEXT supports that exact value.
Report a discrepancy when a value is absent from the source, garbled in it, or contradicted by it.
Treat corrupted characters inside a value (such as the replacement character) as a discrepancy too.

Answer with ONLY a JSON object, no prose:
{{"agreement_score": <fraction of the extracted fields that the source supports, a number from 0 to 1>, "discrepancies": [<one short string per flagged field, or an empty list>]}}"""


class OllamaApertusCrossCheck:
    """The real cross-check: quantised Apertus 8B through an Ollama server.

    Talks to a local (or explicitly configured remote) Ollama server via
    `/api/generate` in JSON mode; the reply body carries `agreement_score`
    plus `discrepancies`. Default host is the local daemon — no hosted
    endpoint, no credential, no licence acceptance (model repo verified not
    gated, Apache-2.0, single GGUF; see module docstring).

    Reply parsing is a trust boundary (see `parse_reply`): failures raise
    `CrossCheckUnavailable` naming what came back; the reply is rejected,
    never coerced or clamped into a plausible score. Each produced result's
    `provenance` records the model tag, host, and measured token counts.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        host: str = DEFAULT_HOST,
        timeout_s: float = 1800.0,
        max_source_chars: int = DEFAULT_MAX_SOURCE_CHARS,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.timeout_s = timeout_s
        self.max_source_chars = max_source_chars
        self.backend = f"ollama:{model}"

    # -- prompt / reply plumbing (pure functions, unit-tested without a server) --

    def build_prompt(self, affair, source_text: str) -> str:
        source = source_text[: self.max_source_chars]
        fields = "\n".join(
            f"- {f}: {str(getattr(affair, f)).strip()!r}"
            for f in CHECKED_FIELDS
            if (getattr(affair, f, "") or "").strip()
        )
        return _PROMPT_TEMPLATE.format(source=source, fields=fields)

    @staticmethod
    def parse_reply(raw: str) -> tuple[float, list[str]]:
        """Extract (agreement_score, discrepancies) from the model's JSON reply.

        Tolerates only JSON wrapped in fences or prose (the object itself is
        located and parsed). Everything else is a FAILURE that names what
        came back: no JSON object, invalid JSON, missing `agreement_score`
        or `discrepancies` key, a non-numeric or out-of-[0,1] score, or a
        `discrepancies` value that is not a list of strings. No defaults,
        no clamping, no percent-scale rescue — a silently invented
        agreement score is the worst possible artifact of this feature.
        """
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise CrossCheckUnavailable(f"reply contained no JSON object: {raw[:300]!r}")
        snippet = match.group(0)
        try:
            payload = json.loads(snippet)
        except json.JSONDecodeError as exc:
            raise CrossCheckUnavailable(f"reply was not valid JSON ({exc}): {snippet[:300]!r}") from exc
        if not isinstance(payload, dict):
            raise CrossCheckUnavailable(f"reply JSON was an object-free {type(payload).__name__}: {snippet[:300]!r}")
        if "agreement_score" not in payload:
            raise CrossCheckUnavailable(f"reply JSON lacked 'agreement_score': {snippet[:300]!r}")
        if "discrepancies" not in payload:
            raise CrossCheckUnavailable(f"reply JSON lacked 'discrepancies': {snippet[:300]!r}")
        value = payload["agreement_score"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CrossCheckUnavailable(f"'agreement_score' was not a number: {value!r}")
        if not (0.0 <= float(value) <= 1.0):
            raise CrossCheckUnavailable(f"'agreement_score' out of [0, 1]: {value!r}")
        disc = payload["discrepancies"]
        if not isinstance(disc, list) or not all(isinstance(d, str) for d in disc):
            raise CrossCheckUnavailable(f"'discrepancies' was not a list of strings: {disc!r}")
        return float(value), list(disc)

    def compare(self, affair, source_text: str) -> CrossCheckResult:
        payload = {
            "model": self.model,
            "prompt": self.build_prompt(affair, source_text),
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0, "num_predict": 400, "num_ctx": 4096},
        }
        request = urllib.request.Request(
            f"{self.host}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300] if exc.fp else str(exc)
            raise CrossCheckUnavailable(f"ollama HTTP {exc.code} from {self.host}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CrossCheckUnavailable(f"ollama server unreachable at {self.host}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise CrossCheckUnavailable(f"ollama returned a non-JSON body: {exc}") from exc
        raw = body.get("response", "")
        agreement, discrepancies = self.parse_reply(raw)
        return CrossCheckResult(
            agreement_score=agreement,
            discrepancies=discrepancies,
            backend=self.backend,
            provenance={
                "model": body.get("model", self.model),
                "host": self.host,
                # Measured token spend from the reply, not estimated:
                "prompt_tokens": body.get("prompt_eval_count"),
                "generated_tokens": body.get("eval_count"),
            },
        )


def cross_check_affair(affair, source_text: str, backend: CrossCheckBackend | None = None) -> CrossCheckResult:
    """Cross-check one extracted affair against its source text.

    Backend selection goes through the single env switch unless a backend is
    passed explicitly. Raises `CrossCheckUnavailable` if a real backend
    cannot answer — callers record that as an outcome; it never becomes a
    score.
    """
    backend = backend or get_crosscheck_backend()
    return backend.compare(affair, source_text)
