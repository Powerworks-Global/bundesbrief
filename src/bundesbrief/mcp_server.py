"""
MCP server exposing the Trust Contract pipeline as tools for an agent client.

Same sample-data pipeline as api.py, wrapped as MCP tools instead of HTTP routes —
so an agent (not just a human hitting /docs) can list affairs, pull a full trust
contract, and verify the ledger before treating a record as ground truth.
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from bundesbrief.ledger import Ledger
from bundesbrief.models import TrustContract
from bundesbrief.pipeline import process_sample_data

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "sample_affairs"
LEDGER_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "mcp_ledger.jsonl"

SYSTEM_PROMPT = (
    "Bundesbrief wraps extracted Swiss parliamentary affairs in a Trust Contract: a "
    "confidence score (schema completeness, OCR noise, source staleness) gating whether "
    "a record is safe to Act on, needs human Suggest-review, or must Halt. Always check "
    "is_publication_permitted before treating a record as ground truth, and use "
    "verify_ledger to confirm the underlying decision log hasn't been tampered with."
)

_contracts: dict[str, TrustContract] = {}


def _ensure_seeded() -> None:
    """Runs the sample-data pipeline once, lazily, on first tool call."""
    if _contracts:
        return
    if LEDGER_PATH.exists():
        LEDGER_PATH.unlink()
    for contract in process_sample_data(DATA_DIR, LEDGER_PATH):
        _contracts[contract.affair_id] = contract


def register_tools(mcp: FastMCP) -> None:
    """Register Bundesbrief tools with the MCP server."""

    @mcp.tool()
    async def list_affairs() -> list[dict]:
        """List every processed parliamentary affair with its trust mode | affairs, trust contracts, parliamentary records, extraction confidence | Use to see what's been extracted and whether each record is safe to use | Returns affair_id, confidence_score, mode (ACT/SUGGEST/HALT), and is_publication_permitted for each record. See also: get_affair, verify_ledger."""
        _ensure_seeded()
        return [
            {
                "affair_id": c.affair_id,
                "confidence_score": c.confidence_score,
                "mode": c.current_mode.value,
                "is_publication_permitted": c.is_publication_permitted,
            }
            for c in _contracts.values()
        ]

    @mcp.tool()
    async def get_affair(affair_id: str) -> dict:
        """Get the full Trust Contract for one parliamentary affair by ID | trust contract, confidence score, telemetry, affair detail | Use when you have an affair_id from list_affairs and need the full confidence breakdown before deciding whether to act on it | Returns the complete TrustContract: confidence score, telemetry vector, policy thresholds, and payload hash. See also: list_affairs.

        Args:
            affair_id: The affair identifier, e.g. 'GR-2026-0412'. Get this from list_affairs first.
        """
        _ensure_seeded()
        contract = _contracts.get(affair_id)
        if contract is None:
            return {"error": f"Unknown affair_id '{affair_id}', or it was Halted before a contract existed"}
        return contract.model_dump(mode="json")

    @mcp.tool()
    async def verify_ledger() -> dict:
        """Verify the justification ledger's hash chain is untampered | ledger verify, tamper check, audit trail, hash chain | Use before trusting any Trust Contract output, to confirm the underlying decision log hasn't been altered after the fact | Returns valid (bool) and the number of entries checked. See also: list_affairs, get_affair."""
        _ensure_seeded()
        ledger = Ledger(LEDGER_PATH)
        entries = 0
        if LEDGER_PATH.exists():
            with LEDGER_PATH.open(encoding="utf-8") as f:
                entries = sum(1 for _ in f)
        return {"valid": ledger.verify(), "entries": entries}


def create_server() -> FastMCP:
    """Create and configure the MCP server with all tools registered."""
    mcp = FastMCP(name="bundesbrief", instructions=SYSTEM_PROMPT)
    register_tools(mcp)
    return mcp
