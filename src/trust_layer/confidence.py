"""Pluggable confidence scoring.

A *dimension* is a named, weighted signal that contributes to an overall
confidence score in ``[0, 1]``. The three canonical dimensions are
completeness, noise and freshness, but callers may supply any dimensions
they like.

A weight may be given as a plain number (``completeness=0.5``) or as a
``Dimension`` that additionally carries a normaliser: a function mapping the
raw metric onto ``[0, 1]``. The normaliser lets each domain decide how a raw
value (e.g. "12% OCR noise") becomes a 0..1 confidence contribution.

Weights are normalised to sum to 1 before scoring, so callers may pass
relative weights without worrying about the total.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping

# A normaliser maps a raw metric value onto [0, 1] (higher = better).
Normaliser = Callable[[float], float]


def _clamp(value: float) -> float:
    """Clamp a value into [0, 1]."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def normalise(value: float) -> float:
    """The default normaliser: clamp the value into [0, 1]."""
    return _clamp(value)


@dataclass(frozen=True)
class Dimension:
    """A weighted signal and how to normalise it onto [0, 1].

    Attributes:
        name:        The dimension's name (e.g. ``"completeness"``).
        weight:      Relative importance; may be any non-negative number.
        normalise:   Maps the raw metric onto [0, 1]. Defaults to clamping.
    """

    name: str
    weight: float = 1.0
    normalise: Normaliser = normalise


# Convenience constructors for the three canonical dimensions.
def default_dimensions(
    completeness: float = 0.5,
    noise: float = 0.3,
    freshness: float = 0.2,
) -> dict[str, Dimension]:
    """Build the canonical three dimensions with the given relative weights."""
    return {
        "completeness": Dimension("completeness", completeness),
        "noise": Dimension("noise", noise),
        "freshness": Dimension("freshness", freshness),
    }


@dataclass(frozen=True)
class Confidence:
    """The result of scoring: an overall score plus a per-dimension breakdown.

    ``score`` is the weighted mean of the normalised dimensions and always
    lies in ``[0, 1]``. ``weights`` holds the normalised (sum-to-1) weight
    actually used, so the breakdown is transparent and reproducible.
    """

    score: float
    breakdown: Mapping[str, float] = field(default_factory=dict)
    weights: Mapping[str, float] = field(default_factory=dict)


class ConfidenceScorer:
    """A pluggable scorer: weighted, normalised combination of dimensions.

    Dimensions may be provided in two ways:

    * a mapping of name -> weight (number), using the default clamp
      normaliser; or
    * a mapping of name -> ``Dimension``, for full control over normalisation.
    """

    def __init__(self, dimensions: Mapping[str, Dimension | float] | None = None):
        if dimensions is None:
            dimensions = default_dimensions()
        self._dims: dict[str, Dimension] = {}
        for name, spec in dimensions.items():
            if isinstance(spec, Dimension):
                self._dims[name] = spec
            else:
                self._dims[name] = Dimension(name, spec)

    @property
    def dimensions(self) -> tuple[str, ...]:
        return tuple(self._dims.keys())

    def _normalised_weights(self) -> dict[str, float]:
        total = sum(d.weight for d in self._dims.values())
        if total <= 0:
            raise ValueError("At least one dimension must have a positive weight.")
        return {name: d.weight / total for name, d in self._dims.items()}

    def score(self, metrics: Mapping[str, float]) -> Confidence:
        """Score a mapping of dimension-name -> raw metric.

        Any metric key without a matching dimension is ignored. Any dimension
        with a missing metric is treated as 0.0.
        """
        weights = self._normalised_weights()
        breakdown: dict[str, float] = {}
        total = 0.0
        for name, dim in self._dims.items():
            raw = metrics.get(name, 0.0)
            normalised_value = _clamp(dim.normalise(raw))
            breakdown[name] = normalised_value
            total += weights[name] * normalised_value
        return Confidence(score=_clamp(total), breakdown=breakdown, weights=weights)


# Convenience: a scorer factory returning a function, for callers who prefer
# a bare callable as their "scorer" plug-in.
def make_scorer(dimensions: Mapping[str, Dimension | float] | None = None) -> Callable[[Mapping[str, float]], Confidence]:
    scorer = ConfidenceScorer(dimensions)
    return scorer.score