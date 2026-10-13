"""Tamper-evident, append-only ledger.

Every decision is written as one JSON line whose hash is chained to the
previous entry's hash (the first entry chains to a fixed genesis hash). The
``verify()`` function re-walks the whole chain and reports any mutation:
a re-ordered, deleted, inserted or edited line breaks the hash chain.

The ledger is intentionally domain-agnostic: an entry is just a dict that
must contain an ``id`` (a stable identifier) and a ``payload``. Everything
else is added by the library.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

GENESIS_HASH = "0" * 64


class LedgerError(Exception):
    """Raised for any structural or integrity problem in a ledger."""


@dataclass(frozen=True)
class LedgerEntry:
    """One verified ledger entry.

    ``payload`` is whatever the caller stored; ``entry`` is the raw stored
    dict (including the bookkeeping fields). ``hash`` is the hash of this
    entry's canonical JSON, which the next entry chains onto.
    """

    entry: Mapping[str, Any]
    hash: str


def _canonical(entry: Mapping[str, Any]) -> bytes:
    """The exact bytes that are hashed: the entry minus its own 'hash'."""
    body = {k: v for k, v in entry.items() if k != "hash"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_entry(prev_hash: str, record_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Construct a ledger entry (not yet hashed) chaining onto ``prev_hash``."""
    return {
        "id": record_id,
        "prev_hash": prev_hash,
        "payload": payload,
    }


class Ledger:
    """Append-only JSONL ledger with a SHA-256 hash chain.

    ``verify()`` is a pure function over the file contents (you may also call
    the module-level ``verify``), so the ledger can be audited independently
    of this object.
    """

    def __init__(self, path: str):
        self.path = path

    def append(self, record_id: str, payload: Mapping[str, Any]) -> LedgerEntry:
        """Append one entry and return it (with its hash).

        ``record_id`` should be stable and unique for the record being logged;
        ``payload`` is the caller's arbitrary, JSON-serialisable data.
        """
        prev_hash = self._last_hash()
        entry = build_entry(prev_hash, record_id, payload)
        digest = sha256(_canonical(entry))
        entry["hash"] = digest
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")
        return LedgerEntry(entry=entry, hash=digest)

    def _last_hash(self) -> str:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                last = None
                for last in fh:
                    pass
        except FileNotFoundError:
            return GENESIS_HASH
        if last is None:
            return GENESIS_HASH
        line = last.strip()
        if not line:
            return GENESIS_HASH
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LedgerError(f"Corrupt (non-JSON) line at end of ledger: {exc}") from exc
        return data.get("hash", GENESIS_HASH)

    def verify(self) -> list[LedgerEntry]:
        """Walk the whole chain and return the entries, raising on tampering."""
        return verify(self.path)


def verify(path: str) -> list[LedgerEntry]:
    """Verify the integrity of a ledger file.

    Returns the entries in order. Raises ``LedgerError`` on the first
    detected problem (non-JSON line, missing/blank hash, a broken hash link,
    or a hash that does not match its own entry's contents).
    """
    entries: list[LedgerEntry] = []
    prev_hash = GENESIS_HASH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return entries

    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LedgerError(f"Line {line_no}: not valid JSON ({exc}).") from exc
        if not isinstance(data, dict):
            raise LedgerError(f"Line {line_no}: entry is not a JSON object.")

        digest = data.get("hash")
        if not isinstance(digest, str) or len(digest) != 64:
            raise LedgerError(f"Line {line_no}: missing or malformed 'hash'.")

        if data.get("prev_hash") != prev_hash:
            raise LedgerError(
                f"Line {line_no}: broken chain (prev_hash does not match)."
            )

        if sha256(_canonical(data)) != digest:
            raise LedgerError(f"Line {line_no}: content hash mismatch (tampered).")

        prev_hash = digest
        entries.append(LedgerEntry(entry=data, hash=digest))

    return entries