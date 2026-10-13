"""trust-layer: wrap any ingestion/extraction step with score -> gate -> ledger.

Extracted from the Bundesbrief pattern (a Swiss parliamentary-PDF extraction
project) as a domain-agnostic building block. See the README for the design
and an honest "what this is and isn't" section.
"""

from .confidence import Confidence, ConfidenceScorer, Dimension, default_dimensions, make_scorer
from .gate import Gate, Verdict
from .ledger import Ledger, LedgerEntry, LedgerError, verify
from .trust import Decision, EvaluationError, TrustLayer

__all__ = [
    "Confidence",
    "ConfidenceScorer",
    "Dimension",
    "default_dimensions",
    "make_scorer",
    "Gate",
    "Verdict",
    "Ledger",
    "LedgerEntry",
    "LedgerError",
    "verify",
    "Decision",
    "EvaluationError",
    "TrustLayer",
]

__version__ = "0.1.0"
