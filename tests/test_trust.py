import unittest

from bundesbrief.models import TrustExecutionPolicy, TrustTelemetryVector, AgentExecutionMode
from bundesbrief.trust import compute_confidence, noise_score, freshness_score, schema_completeness


class TestThresholdEvaluation(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = TrustExecutionPolicy(act_threshold=0.90, suggest_threshold=0.70, halt_threshold=0.69)

    def test_act_boundary(self) -> None:
        self.assertEqual(self.policy.evaluate(0.90), AgentExecutionMode.ACT)
        self.assertEqual(self.policy.evaluate(1.0), AgentExecutionMode.ACT)

    def test_suggest_band(self) -> None:
        self.assertEqual(self.policy.evaluate(0.70), AgentExecutionMode.SUGGEST)
        self.assertEqual(self.policy.evaluate(0.89), AgentExecutionMode.SUGGEST)

    def test_halt_below_floor(self) -> None:
        self.assertEqual(self.policy.evaluate(0.69), AgentExecutionMode.HALT)
        self.assertEqual(self.policy.evaluate(0.0), AgentExecutionMode.HALT)


class TestConfidenceScoring(unittest.TestCase):
    def test_perfect_signals_score_near_one(self) -> None:
        telemetry = TrustTelemetryVector(
            fields_expected=5, fields_found=5, ocr_noise_ratio=0.0, source_age_days=0.0
        )
        self.assertGreaterEqual(compute_confidence(telemetry), 0.99)

    def test_missing_fields_and_noise_degrade_score(self) -> None:
        clean = TrustTelemetryVector(fields_expected=5, fields_found=5, ocr_noise_ratio=0.0, source_age_days=0.0)
        degraded = TrustTelemetryVector(fields_expected=5, fields_found=2, ocr_noise_ratio=0.3, source_age_days=0.0)
        self.assertGreater(compute_confidence(clean), compute_confidence(degraded))

    def test_staleness_degrades_score_independent_of_extraction_quality(self) -> None:
        fresh = TrustTelemetryVector(
            fields_expected=5, fields_found=5, ocr_noise_ratio=0.0, source_age_days=0.0, max_acceptable_age_days=100.0
        )
        stale = TrustTelemetryVector(
            fields_expected=5,
            fields_found=5,
            ocr_noise_ratio=0.0,
            source_age_days=100.0,
            max_acceptable_age_days=100.0,
        )
        self.assertGreater(compute_confidence(fresh), compute_confidence(stale))

    def test_score_is_bounded(self) -> None:
        extreme = TrustTelemetryVector(fields_expected=5, fields_found=0, ocr_noise_ratio=1.0, source_age_days=1e6)
        score = compute_confidence(extreme)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_subscores_individually(self) -> None:
        t = TrustTelemetryVector(fields_expected=4, fields_found=2, ocr_noise_ratio=0.25, source_age_days=50.0)
        self.assertAlmostEqual(schema_completeness(t), 0.5)
        self.assertAlmostEqual(noise_score(t), 0.75)
        self.assertAlmostEqual(freshness_score(t), 1.0 - 50.0 / t.max_acceptable_age_days)


if __name__ == "__main__":
    unittest.main()
