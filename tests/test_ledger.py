import json
import tempfile
import unittest
from pathlib import Path

from bundesbrief.ledger import Ledger
from bundesbrief.models import TrustContract, TrustExecutionPolicy, TrustTelemetryVector, now_utc


def _fake_contract(affair_id: str) -> TrustContract:
    return TrustContract(
        contract_id=f"tc-{affair_id}",
        affair_id=affair_id,
        confidence_score=0.95,
        evaluated_at=now_utc(),
        telemetry=TrustTelemetryVector(fields_expected=5, fields_found=5, ocr_noise_ratio=0.0, source_age_days=0.0),
        policy=TrustExecutionPolicy(),
        payload_hash="deadbeef",
    )


class TestLedger(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.jsonl"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_append_chains_hashes(self) -> None:
        ledger = Ledger(self.path)
        e1 = ledger.append(_fake_contract("A1"))
        e2 = ledger.append(_fake_contract("A2"))
        self.assertEqual(e2.previous_hash, e1.entry_hash)

    def test_verify_passes_on_untampered_chain(self) -> None:
        ledger = Ledger(self.path)
        for i in range(5):
            ledger.append(_fake_contract(f"A{i}"))
        self.assertTrue(ledger.verify())

    def test_verify_fails_if_an_entry_is_tampered(self) -> None:
        ledger = Ledger(self.path)
        ledger.append(_fake_contract("A1"))
        ledger.append(_fake_contract("A2"))

        lines = self.path.read_text(encoding="utf-8").splitlines()
        tampered = json.loads(lines[0])
        tampered["contract"]["confidence_score"] = 0.01  # mutate after the fact
        lines[0] = json.dumps(tampered)
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        self.assertFalse(ledger.verify())


if __name__ == "__main__":
    unittest.main()
