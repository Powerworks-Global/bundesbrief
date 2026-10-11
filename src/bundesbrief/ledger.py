"""
Append-only, hash-chained justification ledger — the Reconstruction mechanism.

Deliberately the smallest possible version of this pattern (JSONL on disk, no
database), same philosophy as Rütli's WORM-mirrored event ledger: the
guarantee that matters for an MVP is "tampering is detectable," not "this
scales to production volume." See docs/adrs/ADR-001.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bundesbrief.models import TrustContract

_GENESIS_HASH = "0" * 64


class LedgerEntry:
    def __init__(self, contract: TrustContract, previous_hash: str):
        self.contract = contract
        self.previous_hash = previous_hash
        self.entry_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        payload = self.contract.model_dump_json() + self.previous_hash
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {
            "contract": json.loads(self.contract.model_dump_json()),
            "previous_hash": self.previous_hash,
            "entry_hash": self.entry_hash,
        }


class Ledger:
    """A single hash-chained JSONL file. `verify()` walks the whole chain."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def _last_hash(self) -> str:
        if self.path.stat().st_size == 0:
            return _GENESIS_HASH
        with self.path.open("r", encoding="utf-8") as f:
            last_line = f.readlines()[-1]
        return json.loads(last_line)["entry_hash"]

    def append(self, contract: TrustContract) -> LedgerEntry:
        entry = LedgerEntry(contract, previous_hash=self._last_hash())
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")
        return entry

    def verify(self) -> bool:
        """Re-walk the chain; returns False the moment a hash doesn't match."""
        previous_hash = _GENESIS_HASH
        if not self.path.exists() or self.path.stat().st_size == 0:
            return True
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                contract = TrustContract.model_validate(row["contract"])
                expected = hashlib.sha256(
                    (contract.model_dump_json() + previous_hash).encode("utf-8")
                ).hexdigest()
                if expected != row["entry_hash"] or row["previous_hash"] != previous_hash:
                    return False
                previous_hash = row["entry_hash"]
        return True
