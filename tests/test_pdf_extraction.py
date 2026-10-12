"""Tests for the real PDF extraction path — run against actual generated
PDF bytes (reportlab), never mocked extraction."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bundesbrief.extraction import EXPECTED_FIELDS, extract_pdf

from pdftools import CLEAN_LINES, NOISY_LINES, write_pdf

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "sample_affairs"


class TestPdfExtraction(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_clean_pdf_yields_full_affair(self) -> None:
        pdf = write_pdf(self.dir / "clean.pdf", CLEAN_LINES)
        result = extract_pdf(pdf)
        self.assertIsNone(result.error)
        self.assertIsNotNone(result.affair)
        self.assertEqual(result.affair.affair_id, "GR-2026-0412")
        self.assertEqual(result.affair.canton, "Zürich")
        self.assertEqual(result.affair.status, "In Beratung")
        self.assertEqual(result.affair.date, "2026-09-15")
        self.assertEqual(result.fields_found, result.fields_expected)
        self.assertEqual(result.fields_expected, len(EXPECTED_FIELDS))

    def test_missing_fields_pdf_finds_fewer_fields(self) -> None:
        pdf = write_pdf(self.dir / "partial.pdf", CLEAN_LINES[:3])
        result = extract_pdf(pdf)
        self.assertIsNotNone(result.affair)  # affair_id present -> affair exists
        self.assertLess(result.fields_found, result.fields_expected)

    def test_no_affair_id_pdf_yields_no_affair(self) -> None:
        pdf = write_pdf(self.dir / "no_id.pdf", CLEAN_LINES[1:])
        result = extract_pdf(pdf)
        self.assertIsNone(result.affair)
        self.assertEqual(result.fields_found, result.fields_expected - 1)

    def test_empty_pdf_does_not_crash(self) -> None:
        pdf = write_pdf(self.dir / "blank.pdf", [""])
        result = extract_pdf(pdf)
        self.assertIsNone(result.error)
        self.assertIsNone(result.affair)
        self.assertEqual(result.fields_found, 0)

    def test_multifield_across_pages(self) -> None:
        pdf = write_pdf(self.dir / "multi.pdf", CLEAN_LINES, pages=3)
        result = extract_pdf(pdf)
        self.assertIsNotNone(result.affair)
        self.assertEqual(result.fields_found, result.fields_expected)

    def test_noisier_pdf_scores_higher_noise_than_clean(self) -> None:
        clean = extract_pdf(write_pdf(self.dir / "clean.pdf", CLEAN_LINES))
        noisy = extract_pdf(write_pdf(self.dir / "noisy.pdf", NOISY_LINES))
        self.assertGreater(noisy.ocr_noise_ratio, clean.ocr_noise_ratio)
        # The noise sub-scores are the reason, and they are inspectable.
        self.assertIsNotNone(noisy.noise)
        self.assertGreater(
            noisy.noise.components.lone_char_ratio, clean.noise.components.lone_char_ratio
        )

    def test_extraction_result_carries_named_sub_scores(self) -> None:
        result = extract_pdf(write_pdf(self.dir / "clean.pdf", CLEAN_LINES))
        comp = result.noise.components
        self.assertGreaterEqual(comp.garbage_ratio, 0.0)
        self.assertGreaterEqual(comp.lone_char_ratio, 0.0)
        self.assertGreaterEqual(comp.ocr_substitution_ratio, 0.0)


class TestMalformedPdfRecordedNotRaised(unittest.TestCase):
    """The mechanism measured to crash on 2 of 18 real cantonal documents:
    a malformed document must fail as a RECORDED outcome, never as an
    unhandled exception taking the run with it."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_garbage_bytes_recorded_not_raised(self) -> None:
        bad = self.dir / "garbage.pdf"
        bad.write_bytes(b"this is not a pdf at all, just random bytes 1234")
        result = extract_pdf(str(bad))  # must not raise
        self.assertIsNone(result.affair)
        self.assertIsNotNone(result.error)
        self.assertEqual(result.fields_found, 0)
        self.assertEqual(result.fields_expected, len(EXPECTED_FIELDS))

    def test_truncated_pdf_recorded_not_raised(self) -> None:
        full = write_pdf(self.dir / "real.pdf", CLEAN_LINES)
        truncated = self.dir / "truncated.pdf"
        truncated.write_bytes(Path(full).read_bytes()[:120])
        try:
            result = extract_pdf(str(truncated))
        except Exception as exc:  # noqa: BLE001
            self.fail(f"truncated PDF raised {type(exc).__name__}: {exc}")
        self.assertIsNone(result.affair)

    def test_missing_file_recorded_not_raised(self) -> None:
        result = extract_pdf(str(self.dir / "does_not_exist.pdf"))
        self.assertIsNone(result.affair)
        self.assertIsNotNone(result.error)
        self.assertIn("FileNotFoundError", result.error)

    def test_malformed_through_pipeline_returns_none_not_exception(self) -> None:
        from datetime import date

        from bundesbrief.ledger import Ledger
        from bundesbrief.pipeline import process_pdf

        bad = self.dir / "garbage.pdf"
        bad.write_bytes(b"%PDF-1.7\n\x00\x01 broken stream \ufffd\ufffd")
        ledger = Ledger(self.dir / "ledger.jsonl")
        contract = process_pdf(str(bad), document_date=date(2026, 1, 1), ledger=ledger)
        self.assertIsNone(contract)
        self.assertTrue(ledger.verify())  # no half-written entry
        self.assertEqual(ledger.path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
