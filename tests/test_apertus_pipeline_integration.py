"""The cross-check wired into the real pipeline — default fast path, failure
containment, and score invariance. All offline: the default stub backend,
plus a refused localhost port to stand in for an unreachable model server.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from bundesbrief.apertus_crosscheck import REAL_BACKENDS_ENV, CrossCheckResult
from bundesbrief.ledger import Ledger
from bundesbrief.models import TrustTelemetryVector
from bundesbrief.pipeline import (
    CROSSCHECK_AUTO,
    process_document,
    process_sample_data,
    process_sample_data_outcomes,
)
from bundesbrief.trust import compute_confidence

REPO_DATA = Path(__file__).resolve().parent.parent / "data" / "sample_affairs"

DOC = (
    "Geschäft Nr: GR-2026-0412\n"
    "Titel: Motion zur Förderung erneuerbarer Energien\n"
    "Kanton: Zürich\n"
    "Status: In Beratung\n"
    "Datum: 2026-09-15\n"
)


class PipelineCrossCheckBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.ledger_path = self.dir / "ledger.jsonl"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _process(self, cross_check=CROSSCHECK_AUTO):
        return process_document(
            DOC, source_url="file://test", document_date=date(2026, 9, 15),
            ledger=Ledger(self.ledger_path), cross_check=cross_check,
        )


class TestDefaultPathFastAndOffline(PipelineCrossCheckBase):
    def test_default_auto_run_attaches_stub_label_and_keeps_ledger_valid(self) -> None:
        with patch.dict("os.environ", {}, clear=True):  # bare checkout
            contract = self._process()
        self.assertIsNotNone(contract)
        self.assertTrue(contract.telemetry.apertus_backend.startswith("stub:"))
        self.assertTrue(Ledger(self.ledger_path).verify())

    def test_stub_score_never_moves_the_authoritative_confidence(self) -> None:
        """Stub figures are recorded for plumbing visibility but must not feed
        the score — otherwise the near-tautological stub agreement would
        inflate every demo record."""
        with patch.dict("os.environ", {}, clear=True):
            with_cc = self._process(CROSSCHECK_AUTO)
            without_cc = self._process(None)
        self.assertEqual(with_cc.confidence_score, without_cc.confidence_score)

    def test_no_cross_check_record_omits_apertus_keys_entirely(self) -> None:
        contract = self._process(None)
        dumped = contract.telemetry.model_dump_json()
        for key in ("apertus_agreement_score", "apertus_backend", "apertus_discrepancies"):
            self.assertNotIn(key, dumped)


class TestModelFailureContained(PipelineCrossCheckBase):
    """The pipeline stays auditable without a model: an unreachable backend is
    a recorded outcome — the document still extracts, still scores."""

    def test_unreachable_backend_does_not_kill_the_document(self) -> None:
        env = {REAL_BACKENDS_ENV: "1", "BUNDESBRIEF_APERTUS_HOST": "http://127.0.0.1:1"}
        with patch.dict("os.environ", env, clear=True):
            contract = self._process()
        self.assertIsNotNone(contract, "a model failure must never fail the document")
        self.assertTrue(contract.telemetry.apertus_backend.startswith("not-run:"))
        self.assertIn("unreachable", contract.telemetry.apertus_backend)
        # Scored on its deterministic dimensions only:
        deterministic = compute_confidence(
            TrustTelemetryVector(
                fields_expected=contract.telemetry.fields_expected,
                fields_found=contract.telemetry.fields_found,
                ocr_noise_ratio=contract.telemetry.ocr_noise_ratio,
                source_age_days=contract.telemetry.source_age_days,
            )
        )
        self.assertEqual(contract.confidence_score, deterministic)
        self.assertTrue(Ledger(self.ledger_path).verify())

    def test_not_run_marker_is_visible_in_dump(self) -> None:
        env = {REAL_BACKENDS_ENV: "1", "BUNDESBRIEF_APERTUS_HOST": "http://127.0.0.1:1"}
        with patch.dict("os.environ", env, clear=True):
            contract = self._process()
        dumped = contract.telemetry.model_dump_json()
        self.assertIn("not-run:", dumped)  # the record says plainly that it did not run


class TestMeasuredScoresFourthDimension(PipelineCrossCheckBase):
    def test_model_measured_result_feeds_the_score(self) -> None:
        cc = CrossCheckResult(
            agreement_score=0.0, discrepancies=["title: fabricated"], backend="ollama:test-model"
        )
        contract = self._process(cc)
        without = self._process(None)
        self.assertLess(contract.confidence_score, without.confidence_score)
        # Full deterministic disagreement caps at 0.8 -> Suggest, never ACT:
        self.assertLess(contract.confidence_score, 0.90)

    def test_stub_measured_result_does_not_feed_the_score(self) -> None:
        cc_stub = CrossCheckResult(agreement_score=0.0, backend="stub:whatever")
        contract = self._process(cc_stub)
        without = self._process(None)
        self.assertEqual(contract.confidence_score, without.confidence_score)

    def test_unmeasured_distinguishable_from_measured_perfect_agreement(self) -> None:
        perfect = self._process(CrossCheckResult(agreement_score=1.0, backend="ollama:test-model"))
        unmeasured = self._process(None)
        self.assertIsNone(unmeasured.telemetry.apertus_backend)
        self.assertNotIn("apertus_agreement_score", unmeasured.telemetry.model_dump_json())
        # same neutral score value, different record: measured says who measured
        self.assertEqual(perfect.telemetry.apertus_backend, "ollama:test-model")


class TestSampleCorpusScoresUnchanged(PipelineCrossCheckBase):
    """009's duty, run not reasoned: the neutral default keeps today's exact
    numbers on the existing corpus (scores recomputed same-process, so the
    freshness drift across days cannot mask a weight change)."""

    def test_corpus_scores_identical_with_auto_stub_and_with_none(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            auto = process_sample_data(REPO_DATA, self.dir / "auto.jsonl", cross_check=CROSSCHECK_AUTO)
            none = process_sample_data(REPO_DATA, self.dir / "none.jsonl", cross_check=None)
        self.assertEqual(
            [(c.affair_id, c.confidence_score, c.current_mode.value) for c in auto],
            [(c.affair_id, c.confidence_score, c.current_mode.value) for c in none],
        )
        self.assertEqual({c.current_mode.value for c in none}, {"ACT", "SUGGEST", "HALT"})

    def test_outcomes_expose_affair_and_source_for_the_api_surface(self) -> None:
        outcomes = process_sample_data_outcomes(REPO_DATA, self.dir / "o.jsonl", cross_check=None)
        self.assertEqual(len(outcomes), 3)
        for o in outcomes:
            self.assertIn("Geschäft", o.source_text)
            self.assertTrue(o.affair.affair_id)
            self.assertEqual(o.contract.affair_id, o.affair.affair_id)


if __name__ == "__main__":
    unittest.main()
