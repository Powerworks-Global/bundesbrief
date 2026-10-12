"""The inversion property, proven end to end on real generated PDFs.

trust_layer's default normaliser treats a HIGHER raw metric as BETTER. Raw
noise is the opposite (higher = worse), so bundesbrief.trust registers the
noise dimension inverted (`normalise=lambda raw: 1.0 - raw`). This file
proves:

  1. the PROPERTY: a deliberately noisier document scores LOWER confidence
     than a clean one, through the full real path (generated PDF bytes ->
     PyMuPDF extraction -> trust_layer scorer -> TrustContract); and
  2. the HONEST CAVEAT: the property is registration-dependent — with the
     same scorer and the SAME metrics but an uninverted noise dimension,
     the ordering flips. The code under test (trust_layer) applies whatever
     normaliser it is given; the correctness lives in the registration in
     bundesbrief/trust.py, and this suite pins both halves.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from trust_layer import ConfidenceScorer, Dimension

from bundesbrief.extraction import extract_pdf
from bundesbrief.ledger import Ledger
from bundesbrief.pipeline import process_pdf
from bundesbrief.trust import compute_confidence

from pdftools import CLEAN_LINES, NOISY_LINES, write_pdf

DOC_DATE = date(2026, 9, 15)


class TestNoisierScoresLowerEndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_noisier_pdf_contract_scores_lower_confidence(self) -> None:
        ledger = Ledger(self.dir / "ledger.jsonl")
        clean = process_pdf(
            write_pdf(self.dir / "clean.pdf", CLEAN_LINES),
            document_date=DOC_DATE,
            ledger=ledger,
        )
        noisy = process_pdf(
            write_pdf(self.dir / "noisy.pdf", NOISY_LINES),
            document_date=DOC_DATE,
            ledger=ledger,
        )
        self.assertIsNotNone(clean)
        self.assertIsNotNone(noisy)
        # Same fields found on both documents, so completeness and freshness
        # are identical — noise is the only term that can move.
        self.assertEqual(
            clean.telemetry.fields_found, noisy.telemetry.fields_found
        )
        self.assertEqual(clean.telemetry.source_age_days, noisy.telemetry.source_age_days)
        self.assertGreater(noisy.telemetry.ocr_noise_ratio, clean.telemetry.ocr_noise_ratio)
        # THE PROPERTY:
        self.assertLess(noisy.confidence_score, clean.confidence_score)
        self.assertTrue(ledger.verify())

    def test_noisier_raw_noise_alone_lowers_confidence(self) -> None:
        """Same property at the scorer boundary, no PDFs involved."""
        clean_telemetry = _telemetry(noise=0.0)
        noisy_telemetry = _telemetry(noise=0.6)
        self.assertLess(
            compute_confidence(noisy_telemetry), compute_confidence(clean_telemetry)
        )


class TestInversionIsRegistrationDependent(unittest.TestCase):
    """Documents the failure mode the inversion fixes: register the raw
    noise metric WITHOUT the normaliser and trust_layer — correctly, by its
    own contract — scores the noisier document as MORE confident."""

    def test_uninverted_noise_dimension_would_score_noisier_higher(self) -> None:
        uninverted = ConfidenceScorer(
            {
                "completeness": Dimension("completeness", 0.5),
                "noise": Dimension("noise", 0.3),  # default clamp: higher raw = better
                "freshness": Dimension("freshness", 0.2),
            }
        )
        clean = uninverted.score({"completeness": 1.0, "noise": 0.0, "freshness": 0.5})
        noisy = uninverted.score({"completeness": 1.0, "noise": 0.6, "freshness": 0.5})
        self.assertGreater(noisy.score, clean.score)  # the demonstrated wrong behaviour

    def test_registered_inverted_dimension_flips_it(self) -> None:
        from bundesbrief.trust import _SCORER

        clean = _SCORER.score({"completeness": 1.0, "noise": 0.0, "freshness": 0.5})
        noisy = _SCORER.score({"completeness": 1.0, "noise": 0.6, "freshness": 0.5})
        self.assertLess(noisy.score, clean.score)


def _telemetry(noise: float):
    from bundesbrief.models import TrustTelemetryVector

    return TrustTelemetryVector(
        fields_expected=5,
        fields_found=5,
        ocr_noise_ratio=noise,
        source_age_days=27.0,
    )


if __name__ == "__main__":
    unittest.main()
