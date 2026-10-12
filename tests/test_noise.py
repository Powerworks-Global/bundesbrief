"""Tests for bundesbrief.noise — the named-sub-score noise heuristic
ported from the pdf-extract repository, run against real document text."""

from __future__ import annotations

import unittest
from pathlib import Path

from bundesbrief.noise import noise_score

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "sample_affairs"


class TestNoiseHeuristic(unittest.TestCase):
    def test_clean_text_scores_low(self) -> None:
        text = (DATA_DIR / "clean.txt").read_text(encoding="utf-8")
        self.assertLess(noise_score(text).score, 0.2)

    def test_replacement_characters_raise_score(self) -> None:
        clean = noise_score("Kanton: Zürich")
        noisy = noise_score("Kant\ufffdn: Z\ufffdrich \ufffd\ufffd\ufffd")
        self.assertGreater(noisy.score, clean.score)
        self.assertGreater(noisy.components.replacement_ratio, clean.components.replacement_ratio)

    def test_lone_characters_raise_score(self) -> None:
        clean = noise_score("Motion zur Förderung erneuerbarer Energien")
        noisy = noise_score("M o t i o n  z u r  F ö r d e r u n g")
        self.assertGreater(noisy.score, clean.score)
        self.assertGreater(noisy.components.lone_char_ratio, clean.components.lone_char_ratio)

    def test_garbage_control_characters_raise_score(self) -> None:
        clean = noise_score("Normal words here and more")
        noisy = noise_score("Normal words \x00 \x01 here \ue000 and more")
        self.assertGreater(noisy.score, clean.score)
        self.assertGreater(noisy.components.garbage_ratio, clean.components.garbage_ratio)

    def test_ocr_substitutions_flagged_in_components(self) -> None:
        noisy = noise_score("l1 O0 S5 rncl INV-2026")
        self.assertGreater(noisy.components.ocr_substitution_ratio, 0.0)

    def test_score_is_bounded(self) -> None:
        pathological = "\x00\x01\x02\ufffd\ue000\ue001 " * 50
        result = noise_score(pathological)
        self.assertGreaterEqual(result.score, 0.0)
        self.assertLessEqual(result.score, 1.0)

    def test_empty_text_scores_zero_and_does_not_crash(self) -> None:
        result = noise_score("")
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.words_total, 0)

    def test_components_are_exposed(self) -> None:
        comp = noise_score("Some ordinary text here.").components
        for value in (
            comp.garbage_ratio,
            comp.lone_char_ratio,
            comp.replacement_ratio,
            comp.ocr_substitution_ratio,
        ):
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_custom_weights_are_applied(self) -> None:
        text = "a b c d e"
        default = noise_score(text)
        weighted = noise_score(text, weights={"lone_char": 0.0})
        self.assertLessEqual(weighted.score, default.score)


if __name__ == "__main__":
    unittest.main()
