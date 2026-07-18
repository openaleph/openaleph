"""
Entity comparison and suggestion logic for cross-referencing.

Extracted from process.py to separate comparison concerns from pipeline orchestration.
"""

import logging
from functools import cache
from typing import TypeAlias, TypedDict

import followthemoney
from followthemoney import E, compare
from followthemoney.proxy import EntityProxy
from followthemoney.types import registry
from followthemoney_compare.models import GLMBernoulli2EEvaluator
from nomenklatura.matching import ScoringConfig, get_algorithm
from nomenklatura.matching.types import ScoringAlgorithm

from aleph.settings import SETTINGS

log = logging.getLogger(__name__)

MODEL = None
FTM_VERSION_STR = f"ftm-{followthemoney.__version__}"

Result: TypeAlias = tuple[float, float | None, str]


class Suggestion(TypedDict):
    left_id: str | None
    right_id: str | None
    score: float
    user: str | None
    source_collection_id: set[int] | None
    target_collection_id: set[int] | None
    method: str | None
    schema: str
    text: list[str]
    countries: list[str]


MAX_NAMES = 30


@cache
def _get_nk_algorithm() -> type[ScoringAlgorithm] | None:
    if SETTINGS.XREF_ALGORITHM is not None:
        return get_algorithm(SETTINGS.XREF_ALGORITHM)


NK_SCORING_CONFIG = ScoringConfig.defaults()


def _load_model():
    """Load the FTM-compare ML model, falling back to None on failure."""
    global MODEL
    if MODEL is not None:
        return MODEL
    try:
        with open(SETTINGS.XREF_MODEL, "rb") as fd:
            MODEL = GLMBernoulli2EEvaluator.from_pickles(fd.read())
        return MODEL
    except FileNotFoundError:
        log.exception(f"Could not find model file: {SETTINGS.XREF_MODEL}")
        SETTINGS.XREF_MODEL = None
        return None


def compare_entities(left: E, right: E) -> Result:
    """Compare two entities using the configured algorithm/model.

    Returns (score, confidence, method).
    Dispatch: nomenklatura algorithm > ML model > followthemoney compare.
    """
    algorithm = _get_nk_algorithm()
    if algorithm is not None:
        result = algorithm.compare(left, right, NK_SCORING_CONFIG)
        return result.score, None, algorithm.NAME
    if SETTINGS.XREF_MODEL is not None and _load_model() is not None:
        score, confidence = next(zip(*MODEL.predict_proba_std([(left, right)])))
        return score, confidence, MODEL.version
    return compare.compare(left, right), None, FTM_VERSION_STR


def make_suggestion(
    left: EntityProxy,
    right: EntityProxy,
    source_collection_id: set[int] | None = None,
    target_collection_id: set[int] | None = None,
    user: str | None = None,
    score: float | None = None,
    method: str | None = None,
) -> Suggestion:
    """Compare two entities and build a suggestion dict.

    The returned dict can be passed directly to resolver.suggest(**suggestion).
    If score/method are provided, skips re-comparing (used by batch xref).
    """
    if score is None:
        score, _, method = compare_entities(left, right)
    text = set([left.caption, right.caption])
    text.update(left.get_type_values(registry.name)[:MAX_NAMES])
    text.update(right.get_type_values(registry.name)[:MAX_NAMES])
    text.discard(None)
    countries = set(left.get_type_values(registry.country))
    countries.update(right.get_type_values(registry.country))
    return {
        "left_id": left.id,
        "right_id": right.id,
        "score": score,
        "user": user,
        "source_collection_id": source_collection_id,
        "target_collection_id": target_collection_id,
        "method": method,
        "schema": right.schema.name,
        "text": list(text),
        "countries": list(countries),
    }
