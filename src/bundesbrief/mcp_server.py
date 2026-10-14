"""
MCP server exposing the Trust Contract pipeline as tools for an agent client.

Same sample-data pipeline as api.py, wrapped as MCP tools instead of HTTP routes —
so an agent (not just a human hitting /docs) can list affairs, pull a full trust
contract, and verify the ledger before treating a record as ground truth.
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from bundesbrief.apertus_crosscheck import get_crosscheck_backend, log_backend
from bundesbrief.ledger import Ledger
from bundesbrief.models import TrustContract
from bundesbrief.pipeline import SampleOutcome, process_sample_data_outcomes

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "sample_affairs"
LEDGER_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "mcp_ledger.jsonl"

SYSTEM_PROMPT = (
    "Bundesbrief wraps extracted Swiss parliamentary affairs in a Trust Contract: a "
    "confidence score (schema completeness, OCR noise, source staleness, plus an "
    "optional Apertus cross-check agreement dimension) gating whether a record is "
    "safe to Act on, needs human Suggest-review, or must Halt. Always check "
    "is_publication_permitted before treating a record as ground truth, read the "
    "cross_check block's backend label to tell a measured model agreement from a "
    "stub harness figure, and use verify_ledger to confirm the underlying decision "
    "log hasn't been tampered with."
)

_contracts: dict[str, TrustContract] = {}
_outcomes: dict[str, SampleOutcome] = {}


def _ensure_seeded() -> None:
    """Runs the sample-data pipeline once, lazily, on first tool call."""
    if _contracts:
        return
    if LEDGER_PATH.exists():
        LEDGER_PATH.unlink()
    backend = get_crosscheck_backend()
    log_backend(backend)  # names the backend behind every cross_check number below
    for outcome in process_sample_data_outcomes(DATA_DIR, LEDGER_PATH):
        _contracts[outcome.contract.affair_id] = outcome.contract
        _outcomes[outcome.contract.affair_id] = outcome


def _cross_check_block(contract: TrustContract) -> dict:
    """The cross_check view of a contract's telemetry, backend label included.

    Reads what the ledger recorded (no silent re-measurement), and states
    plainly when no cross-check ran — an agent client can always tell a
    measured Apertus agreement from a stub figure from this block alone.
    """
    telemetry = contract.telemetry
    if telemetry.apertus_backend is None:
        return {"ran": False, "reason": "no cross-check was performed for this record"}
    ran = not telemetry.apertus_backend.startswith("not-run:")
    block = {
        "ran": ran,
        "agreement_score": telemetry.apertus_agreement_score,
        "discrepancies": telemetry.apertus_discrepancies or [],
        "backend": telemetry.apertus_backend,
    }
    if not ran:
        block.pop("agreement_score")
        block["reason"] = telemetry.apertus_backend
    return block


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
        """Get the full Trust Contract for one parliamentary affair by ID, including its Apertus cross-check signal | trust contract, confidence score, telemetry, cross-check agreement, affair detail | Use when you have an affair_id from list_affairs and need the full confidence breakdown before deciding whether to act on it | Returns the complete TrustContract: confidence score, telemetry vector, policy thresholds, payload hash, plus a cross_check block (agreement_score, discrepancies, backend label) — the backend label distinguishes a measured model agreement ('ollama:...' / a model tag) from a stub harness figure ('stub:...') or a not-run marker. See also: list_affairs.

        Args:
            affair_id: The affair identifier, e.g. 'GR-2026-0412'. Get this from list_affairs first.
        """
        _ensure_seeded()
        contract = _contracts.get(affair_id)
        if contract is None:
            return {"error": f"Unknown affair_id '{affair_id}', or it was Halted before a contract existed"}
        payload = contract.model_dump(mode="json")
        payload["cross_check"] = _cross_check_block(contract)
        return payload

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
