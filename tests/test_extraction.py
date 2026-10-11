import unittest
from pathlib import Path

from bundesbrief.extraction import extract

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "sample_affairs"


class TestExtraction(unittest.TestCase):
    def test_clean_document_finds_all_fields(self) -> None:
        text = (DATA_DIR / "clean.txt").read_text(encoding="utf-8")
        result = extract(text)
        self.assertIsNotNone(result.affair)
        self.assertEqual(result.fields_found, result.fields_expected)
        self.assertEqual(result.affair.canton, "Zürich")

    def test_degraded_ocr_document_finds_fewer_fields(self) -> None:
        text = (DATA_DIR / "degraded_ocr.txt").read_text(encoding="utf-8")
        clean_text = (DATA_DIR / "clean.txt").read_text(encoding="utf-8")
        degraded_result = extract(text)
        clean_result = extract(clean_text)
        self.assertLess(degraded_result.fields_found, clean_result.fields_found)
        self.assertGreater(degraded_result.ocr_noise_ratio, clean_result.ocr_noise_ratio)

    def test_incomplete_document_still_returns_an_affair_if_id_found(self) -> None:
        text = (DATA_DIR / "incomplete_stale.txt").read_text(encoding="utf-8")
        result = extract(text)
        self.assertIsNotNone(result.affair)
        self.assertLess(result.fields_found, result.fields_expected)

    def test_no_affair_id_returns_no_affair(self) -> None:
        result = extract("This text has no recognizable fields at all.")
        self.assertIsNone(result.affair)


if __name__ == "__main__":
    unittest.main()
