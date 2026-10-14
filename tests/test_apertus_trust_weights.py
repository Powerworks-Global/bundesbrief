"""The rebalanced four-dimension profile and its activation rule (ADR-003).

The deterministic trio keeps its exact internal 0.5/0.3/0.2 ratio rescaled
to share 0.8, and the Apertus agreement gets 0.2 — but ONLY when a real
model measurement is attached. Stub labels and not-run markers must select
today's three-dimension profile, byte-for-byte.
"""

from __future__ import annotations

import unittest

from bundesbrief.models import AgentExecutionMode, TrustExecutionPolicy, TrustTelemetryVector
from bundesbrief.trust import (
    _APERTUS_WEIGHT,
    _FRESHNESS_WEIGHT_4D,
    _NOISE_PENALTY_WEIGHT_4D,
    _SCHEMA_COMPLETENESS_WEIGHT_4D,
    compute_confidence,
)


def _perfect(**apertus) -> TrustTelemetryVector:
    return TrustTelemetryVector(
        fields_expected=5, fields_found=5, ocr_noise_ratio=0.0, source_age_days=0.0, **apertus
    )


class TestWeightSplit(unittest.TestCase):
    def test_weights_are_the_documented_split(self) -> None:
        self.assertAlmostEqual(_APERTUS_WEIGHT, 0.2)
        self.assertAlmostEqual(_SCHEMA_COMPLETENESS_WEIGHT_4D, 0.40)
        self.assertAlmostEqual(_NOISE_PENALTY_WEIGHT_4D, 0.24)
        self.assertAlmostEqual(_FRESHNESS_WEIGHT_4D, 0.16)

    def test_deterministic_ratios_are_preserved_under_rebalancing(self) -> None:
        self.assertAlmostEqual(_SCHEMA_COMPLETENESS_WEIGHT_4D / _NOISE_PENALTY_WEIGHT_4D, 0.5 / 0.3)
        self.assertAlmostEqual(_NOISE_PENALTY_WEIGHT_4D / _FRESHNESS_WEIGHT_4D, 0.3 / 0.2)


class TestProfileSelection(unittest.TestCase):
    def test_perfect_everything_scores_one(self) -> None:
        telemetry = _perfect(apertus_agreement_score=1.0, apertus_backend="ollama:some-model")
        self.assertAlmostEqual(compute_confidence(telemetry), 1.0)

    def test_model_disagreement_caps_below_act(self) -> None:
        """A model-reported zero agreement caps a deterministically perfect
        record at 0.8 -> Suggest: full disagreement blocks auto-publication
        (forces human review) but is not by itself a HALT."""
        telemetry = _perfect(apertus_agreement_score=0.0, apertus_backend="ollama:some-model")
        score = compute_confidence(telemetry)
        self.assertAlmostEqual(score, 0.8)
        self.assertEqual(TrustExecutionPolicy().evaluate(score), AgentExecutionMode.SUGGEST)

    def test_same_vector_without_a_measurement_is_today_three_dim(self) -> None:
        self.assertAlmostEqual(compute_confidence(_perfect()), 1.0)

    def test_stub_and_notrun_labels_do_not_activate_the_fourth_dimension(self) -> None:
        for backend in ("stub:whatever", "not-run: ollama server unreachable"):
            with self.subTest(backend=backend):
                telemetry = _perfect(
                    apertus_agreement_score=0.0,  # would tank the score if 4-dim were active
                    apertus_backend=backend,
                )
                self.assertAlmostEqual(compute_confidence(telemetry), 1.0)


if __name__ == "__main__":
    unittest.main()
