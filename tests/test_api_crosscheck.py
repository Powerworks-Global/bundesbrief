"""REST exposure of the cross-check signal — stub backend, offline.

Uses FastAPI's TestClient; the seeded pipeline runs with the env cleared so
these numbers are the deterministic stub's, labelled as such in every
response. No network, no model.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from bundesbrief.api import app


class TestCrossCheckEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with patch.dict("os.environ", {}, clear=True):
            cls.client = TestClient(app)
            cls.entered = cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)

    def test_cross_check_for_clean_sample_is_labelled_stub(self) -> None:
        response = self.entered.get("/affairs/GR-2026-0412/cross-check")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ran"])
        self.assertEqual(body["agreement_score"], 1.0)
        self.assertTrue(body["backend"].startswith("stub:"))
        self.assertIn("NOT a model measurement", body["note"])

    def test_cross_check_unknown_affair_is_404(self) -> None:
        self.assertEqual(self.entered.get("/affairs/nope/cross-check").status_code, 404)

    def test_affairs_and_ledger_unchanged(self) -> None:
        affairs = self.entered.get("/affairs").json()
        self.assertEqual({a["mode"] for a in affairs}, {"ACT", "SUGGEST", "HALT"})
        verify = self.entered.get("/ledger/verify").json()
        self.assertTrue(verify["valid"])
        self.assertGreaterEqual(verify["entries"], 3)

    def test_get_affair_telemetry_carries_stub_backend_label(self) -> None:
        contract = self.entered.get("/affairs/GR-2026-0412").json()
        telemetry = contract["telemetry"]
        self.assertTrue(telemetry["apertus_backend"].startswith("stub:"))
        # the label alone tells a reader this is not a model measurement:
        self.assertIn("NOT the Apertus model", telemetry["apertus_backend"])


if __name__ == "__main__":
    unittest.main()
