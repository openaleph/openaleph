"""
Cross-reference (xref) package.

Re-exports public API so that `from aleph.logic.xref import ...` continues to work.
"""

from aleph.logic.xref.process import (  # noqa: F401
    SCORE_CUTOFF,
    Match,
    export_matches,
    xref_collection,
    xref_entity,
)
from aleph.logic.xref.resolver import ElasticsearchResolver, get_resolver  # noqa: F401
