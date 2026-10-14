"""Stub-backend tests for the Apertus cross-check — deterministic, no network.

Every test here runs against the DEFAULT stub backend (or against pure
parse/build functions). Nothing in this file needs the model, the Ollama
daemon, or the network; the real backend is exercised only through its
offline-testable halves (prompt building, reply parsing, env selection).
The real-backend run is a separate, recorded, opt-in command — see
scripts/run_apertus_crosscheck.py and docs/adrs/ADR-003.
"""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from bundesbrief.apertus_crosscheck import (
    DEFAULT_HOST,
    DEFAULT_MODEL,
    HOST_ENV,
    MODEL_ENV,
    REAL_BACKENDS_ENV,
    CrossCheckError,
    CrossCheckResult,
    CrossCheckUnavailable,
    OllamaApertusCrossCheck,
    StubApertusCrossCheck,
    get_crosscheck_backend,
    log_backend,
    real_backends_enabled,
)
from bundesbrief.models import ParliamentaryAffair


def _affair(**overrides) -> ParliamentaryAffair:
    fields = {
        "affair_id": "GR-2026-0412",
        "title": "Motion zur Foerderung erneuerbarer Energien",
        "canton": "Zuerich",
        "status": "In Beratung",
        "date": "2026-09-15",
        "source_url": "file://test",
    }
    fields.update(overrides)
    return ParliamentaryAffair(**fields)


SOURCE = (
    "Geschäft Nr: GR-2026-0412\n"
    "Titel: Motion zur Foerderung erneuerbarer Energien\n"
    "Kanton: Zuerich\n"
    "Status: In Beratung\n"
    "Datum: 2026-09-15\n"
)


class TestStubBackend(unittest.TestCase):
    def setUp(self) -> None:
        self.stub = StubApertusCrossCheck()

    def test_verbatim_fields_yield_full_agreement(self) -> None:
        result = self.stub.compare(_affair(), SOURCE)
        self.assertEqual(result.agreement_score, 1.0)
        self.assertEqual(result.discrepancies, [])

    def test_backend_label_is_an_unmistakable_stub_marker(self) -> None:
        result = self.stub.compare(_affair(), SOURCE)
        self.assertTrue(result.backend.startswith("stub:"))
        self.assertIn("NOT the Apertus model", result.backend)
        self.assertTrue(result.is_stub)
        self.assertFalse(result.is_model_measured)

    def test_tampered_value_lowers_agreement_and_names_the_field(self) -> None:
        affair = _affair(canton="Bern")  # source says Zuerich
        result = self.stub.compare(affair, SOURCE)
        self.assertAlmostEqual(result.agreement_score, 4 / 5)
        self.assertEqual(len(result.discrepancies), 1)
        self.assertIn("canton", result.discrepancies[0])

    def test_garbled_value_is_flagged_not_coerced(self) -> None:
        affair = _affair(title="Interpell\ufffdtion betreffend Verkehrssicherheit")
        result = self.stub.compare(affair, SOURCE)
        self.assertLess(result.agreement_score, 1.0)
        self.assertTrue(any("title" in d for d in result.discrepancies))

    def test_no_emitted_values_is_vacuous_and_says_so(self) -> None:
        affair = ParliamentaryAffair(affair_id="", title="", canton="", status="", date="")
        result = self.stub.compare(affair, SOURCE)
        self.assertEqual(result.agreement_score, 1.0)
        self.assertTrue(any("vacuous" in d for d in result.discrepancies))

    def test_determinism(self) -> None:
        first = self.stub.compare(_affair(), SOURCE)
        second = self.stub.compare(_affair(), SOURCE)
        self.assertEqual(first.as_dict(), second.as_dict())

    def test_case_and_diacritic_insensitive_literal_matching(self) -> None:
        source = "Titel: MOTION ZÜR\nKanton: zür\n"
        affair = _affair(title="Motion Zür", canton="ZÜr", affair_id="MOTION", status="zür", date="zür")
        result = self.stub.compare(affair, source)
        self.assertEqual(result.agreement_score, 1.0)


class TestCrossCheckResultValidation(unittest.TestCase):
    """Rejection, not coercion — a bad score is a bug to surface, not clamp."""

    def test_out_of_range_score_rejected(self) -> None:
        for bad in (1.5, -0.001, 100):
            with self.subTest(score=bad), self.assertRaises(ValueError):
                CrossCheckResult(agreement_score=bad, discrepancies=[], backend="x")

    def test_type_validation(self) -> None:
        with self.assertRaises(TypeError):
            CrossCheckResult(agreement_score="0.9")  # no coercion from strings
        with self.assertRaises(TypeError):
            CrossCheckResult(agreement_score=True)  # bool is not a number here
        with self.assertRaises(TypeError):
            CrossCheckResult(agreement_score=0.9, discrepancies="canton: wrong")  # not a list
        with self.assertRaises(TypeError):
            CrossCheckResult(agreement_score=0.9, discrepancies=[{"field": "canton"}])  # not strings

    def test_backend_is_mandatory(self) -> None:
        with self.assertRaises(ValueError):
            CrossCheckResult(agreement_score=0.9, backend="")


class TestBackendSwitch(unittest.TestCase):
    def test_default_is_stub_no_env_needed(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(real_backends_enabled())
            self.assertIsInstance(get_crosscheck_backend(), StubApertusCrossCheck)

    def test_only_exactly_one_enables_the_real_backend(self) -> None:
        for off in ("", "0", "true", "yes", "1 ", "ON"):
            with self.subTest(value=off), patch.dict("os.environ", {REAL_BACKENDS_ENV: off}):
                self.assertFalse(real_backends_enabled())
                self.assertIsInstance(get_crosscheck_backend(), StubApertusCrossCheck)
        with patch.dict("os.environ", {REAL_BACKENDS_ENV: "1"}):
            self.assertTrue(real_backends_enabled())
            self.assertIsInstance(get_crosscheck_backend(), OllamaApertusCrossCheck)

    def test_companion_vars_default_and_override(self) -> None:
        with patch.dict("os.environ", {REAL_BACKENDS_ENV: "1"}, clear=True):
            backend = get_crosscheck_backend()
            self.assertEqual(backend.model, DEFAULT_MODEL)
            self.assertEqual(backend.host, DEFAULT_HOST)
        with patch.dict(
            "os.environ", {REAL_BACKENDS_ENV: "1", MODEL_ENV: "my/model:Q8", HOST_ENV: "http://box:9999"}
        ):
            backend = get_crosscheck_backend()
            self.assertEqual(backend.model, "my/model:Q8")
            self.assertEqual(backend.host, "http://box:9999")
            self.assertEqual(backend.backend, "ollama:my/model:Q8")


class TestReplyParsingTrustBoundary(unittest.TestCase):
    """parse_reply is the hostile-reply boundary: it names failures, never defaults."""

    def test_valid_reply(self) -> None:
        raw = json.dumps({"agreement_score": 0.6, "discrepancies": ["canton: source says Zürich"]})
        self.assertEqual(
            OllamaApertusCrossCheck.parse_reply(raw), (0.6, ["canton: source says Zürich"])
        )

    def test_prose_wrapped_json_is_located_and_parsed(self) -> None:
        raw = 'Sure! {"agreement_score": 1.0, "discrepancies": []} — hope that helps'
        self.assertEqual(OllamaApertusCrossCheck.parse_reply(raw), (1.0, []))

    def test_no_json_fails_naming_the_reply(self) -> None:
        with self.assertRaises(CrossCheckUnavailable) as ctx:
            OllamaApertusCrossCheck.parse_reply("I cannot help with that.")
        self.assertIn("no JSON object", str(ctx.exception))

    def test_invalid_json_fails(self) -> None:
        with self.assertRaises(CrossCheckUnavailable):
            OllamaApertusCrossCheck.parse_reply("{agreement_score: }")

    def test_missing_keys_fail(self) -> None:
        with self.assertRaises(CrossCheckUnavailable) as ctx:
            OllamaApertusCrossCheck.parse_reply('{"discrepancies": []}')
        self.assertIn("agreement_score", str(ctx.exception))
        with self.assertRaises(CrossCheckUnavailable):
            OllamaApertusCrossCheck.parse_reply('{"agreement_score": 0.5}')

    def test_out_of_range_score_fails_without_clamping(self) -> None:
        for bad in (85, 1.01, -3.0):
            payload = {"agreement_score": bad, "discrepancies": []}
            with self.subTest(score=bad), self.assertRaises(CrossCheckUnavailable):
                OllamaApertusCrossCheck.parse_reply(json.dumps(payload))

    def test_non_numeric_score_fails(self) -> None:
        with self.assertRaises(CrossCheckUnavailable):
            OllamaApertusCrossCheck.parse_reply('{"agreement_score": "high", "discrepancies": []}')
        with self.assertRaises(CrossCheckUnavailable):
            OllamaApertusCrossCheck.parse_reply('{"agreement_score": true, "discrepancies": []}')

    def test_discrepancies_not_a_list_of_strings_fails(self) -> None:
        for bad in ('"canton: x"', '[{"field": "canton"}]', "null", "5"):
            raw = '{"agreement_score": 0.5, "discrepancies": ' + bad + "}"
            with self.subTest(discrepancies=bad), self.assertRaises(CrossCheckUnavailable):
                OllamaApertusCrossCheck.parse_reply(raw)

    def test_error_is_a_crosscheck_error_subclass(self) -> None:
        self.assertTrue(issubclass(CrossCheckUnavailable, CrossCheckError))


class TestRealBackendPlumbing(unittest.TestCase):
    def test_prompt_carries_source_and_extracted_fields(self) -> None:
        backend = OllamaApertusCrossCheck()
        prompt = backend.build_prompt(_affair(), SOURCE)
        self.assertIn("SOURCE TEXT", prompt)
        self.assertIn("EXTRACTED FIELDS", prompt)
        self.assertIn("- affair_id: 'GR-2026-0412'", prompt)
        self.assertIn("- canton: 'Zuerich'", prompt)
        self.assertLess(prompt.index("SOURCE TEXT"), prompt.index("EXTRACTED FIELDS"))

    def test_source_is_truncated_to_the_configured_budget(self) -> None:
        backend = OllamaApertusCrossCheck(max_source_chars=50)
        prompt = backend.build_prompt(_affair(), "x" * 500)
        self.assertNotIn("x" * 51, prompt)

    def test_unreachable_server_raises_unavailable_never_a_score(self) -> None:
        backend = OllamaApertusCrossCheck(host="http://127.0.0.1:1", timeout_s=5)
        with self.assertRaises(CrossCheckUnavailable):
            backend.compare(_affair(), SOURCE)


class TestBanners(unittest.TestCase):
    def test_stub_banner_names_harness_validation_and_the_switch(self) -> None:
        out = io.StringIO()
        log_backend(StubApertusCrossCheck(), stream=out)
        text = out.getvalue()
        self.assertIn("HARNESS-VALIDATION", text)
        self.assertIn("NOT submission numbers", text)
        self.assertIn(REAL_BACKENDS_ENV, text)

    def test_real_banner_names_the_model_in_play(self) -> None:
        out = io.StringIO()
        log_backend(OllamaApertusCrossCheck(model="hf.co/Colby/apertus-x:Q4_K_M"), stream=out)
        text = out.getvalue()
        self.assertIn("REAL backend", text)
        self.assertIn("hf.co/Colby/apertus-x:Q4_K_M", text)


if __name__ == "__main__":
    unittest.main()
