"""
A 0-1 heuristic for how garbled an extracted text layer is, with named
sub-scores — vendored behaviourally from the `pdf-extract` project's
`pdf_extract.noise` module (Apache 2.0, same author), adapted only in
packaging.

IMPORTANT -- what this is and is not
------------------------------------
This is a *heuristic estimate of text-layer quality*, NOT a calibrated OCR
confidence score. Real OCR engines expose per-character confidence values
alongside their output; text-layer readers like PyMuPDF do not, because they
read the text layer that already exists in the PDF. On a native
(born-digital) PDF there is no OCR at all, so "OCR confidence" is meaningless
there. On a scanned-then-OCR'd PDF,
the embedded text layer can be genuinely garbled, and that is the case where
this heuristic is most useful: it estimates *how broken the text we already
have* looks, not how confident some OCR engine was.

The score is a weighted combination of several cheap, measurable signals, each
normalised to [0, 1] and clamped. The weights are tunable defaults, not
empirically calibrated ground truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Characters we treat as "garbage": control characters (except newline/tab,
# which are structural), the Unicode replacement character, and private-use
# glyphs that leak out of broken text layers.
_GARBAGE_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ufffd\ue000-\uf8ff]"
)

# Classic OCR substitution pairs (l <-> 1, O <-> 0, etc.). These are only a
# weak signal because they also occur in legitimate text, so they are weighted
# low.
_OCR_PAIRS = [
    ("l", "1"),
    ("1", "l"),
    ("O", "0"),
    ("0", "O"),
    ("S", "5"),
    ("5", "S"),
    ("rn", "m"),
    ("cl", "d"),
]

# A "lone character" is a single letter/digit surrounded by spaces -- the kind
# of broken word an OCR artifact produces where a real word should be.
_LONE_CHAR_RE = re.compile(r"(?<!\S)[A-Za-z0-9](?!\S)")


@dataclass(frozen=True)
class NoiseComponents:
    """Individual sub-scores behind the aggregate noise estimate.

    Each is in [0, 1]; 0 means "clean", 1 means "heavily affected".
    """

    garbage_ratio: float
    lone_char_ratio: float
    replacement_ratio: float
    ocr_substitution_ratio: float


@dataclass
class NoiseScore:
    """The aggregate noise score and the components that produced it.

    Exposing the components keeps the score debuggable and honest: a caller
    can see *why* a document scored the way it did rather than trusting a
    single opaque number.
    """

    score: float
    components: NoiseComponents
    words_total: int
    weights: Dict[str, float] = field(default_factory=dict)


def _word_tokens(text: str) -> List[str]:
    """Split on whitespace; a token may still be punctuation-only."""
    return text.split()


def _garbage_ratio(text: str) -> float:
    if not text:
        return 0.0
    return len(_GARBAGE_RE.findall(text)) / len(text)


def _lone_char_ratio(words: List[str]) -> float:
    if not words:
        return 0.0
    lone = sum(1 for w in words if _LONE_CHAR_RE.fullmatch(w))
    return lone / len(words)


def _replacement_ratio(text: str) -> float:
    if not text:
        return 0.0
    return text.count("\ufffd") / len(text)


def _ocr_substitution_ratio(words: List[str]) -> float:
    """Density of words that contain a known OCR substitution pattern.

    Heuristic and deliberately low-weight: legitimate text contains these
    patterns too (e.g. the digit "10" or the word "monday").
    """
    if not words:
        return 0.0
    hits = 0
    for w in words:
        for a, _b in _OCR_PAIRS:
            if a in w:
                # Only count when it looks like a substitution, not a normal
                # occurrence. This is approximate by design.
                hits += 1
                break
    return hits / len(words)


def noise_score(
    text: str,
    weights: Optional[Dict[str, float]] = None,
) -> NoiseScore:
    """Estimate a 0-1 "noise" score for an extracted text layer.

    ``text`` should be the concatenated extracted text (or a single page's
    text). Higher is worse: 0 means clean, 1 means heavily garbled.

    ``weights`` optionally overrides the default sub-score weights. Unknown
    keys are ignored.
    """
    if weights is None:
        weights = {}
    defaults = {
        "garbage": 0.35,
        "lone_char": 0.30,
        "replacement": 0.25,
        "ocr_substitution": 0.10,
    }
    effective = {**defaults, **{k: v for k, v in weights.items() if k in defaults}}

    words = _word_tokens(text)

    garbage = _garbage_ratio(text)
    lone = _lone_char_ratio(words)
    replacement = _replacement_ratio(text)
    ocr = _ocr_substitution_ratio(words)

    components = NoiseComponents(
        garbage_ratio=garbage,
        lone_char_ratio=lone,
        replacement_ratio=replacement,
        ocr_substitution_ratio=ocr,
    )

    raw = (
        effective["garbage"] * garbage
        + effective["lone_char"] * lone
        + effective["replacement"] * replacement
        + effective["ocr_substitution"] * ocr
    )

    score = max(0.0, min(1.0, raw))

    return NoiseScore(
        score=score,
        components=components,
        words_total=len(words),
        weights=effective,
    )
