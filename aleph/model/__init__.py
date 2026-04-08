"""Public surface for ``aleph.model``.

Re-exports both the SQLAlchemy classes (the ``Alert``, ``Collection``,
``Entity``, ... rows) and the pydantic schemas (``AlertSchema``,
``CollectionSchema``, ``EntitySchema``, ...) so callers can do
``from aleph.model import RoleSchema, EntitySchema``.

Request body schemas live separately in ``aleph.api.requests`` because
they encode an HTTP contract, not a persisted shape, and the data layer
must not depend on the API layer.

The ``__all__`` list below declares the package's public API and
suppresses the ruff F401 ("imported but unused") warning.
"""

from aleph.core import db

# === SQLAlchemy models ===
from aleph.model.alert import Alert, AlertSchema
from aleph.model.bookmark import Bookmark, BookmarkSchema
from aleph.model.collection import (
    Collection,
    CollectionDeepSchema,
    CollectionJobStatus,
    CollectionSchema,
    CollectionStageStatus,
    CollectionStatistics,
    CollectionStatus,
    FacetCounts,
    StatusCounts,
)
from aleph.model.common import (
    APIBaseModel,
    DatedSchema,
    SDict,
    Status,
    make_token,
    model_dump,
)
from aleph.model.discover import (
    DatasetDiscovery,
    MentionedTerms,
    SignificantTerms,
    Term,
)
from aleph.model.document import Document
from aleph.model.entity import (
    Entity,
    EntityExpandSchema,
    EntitySchema,
    EntityTagSchema,
    SimilarSchema,
)
from aleph.model.entityset import (
    DiagramEdge,
    DiagramGrouping,
    DiagramLayout,
    DiagramLayoutSettings,
    DiagramVertex,
    EntitySet,
    EntitySetItem,
    EntitySetItemSchema,
    EntitySetSchema,
    EntitySetType,
    Judgement,
)
from aleph.model.event import (
    Event,
    Events,
    EventSchema,
    NotificationSchema,
)
from aleph.model.export import Export, ExportSchema
from aleph.model.mapping import Mapping, MappingSchema
from aleph.model.permission import Permission, PermissionSchema
from aleph.model.role import Role, RoleSchema, RoleType
from aleph.model.tag import Tag, TagSchema
from aleph.model.xref import (
    CanonicalSchema,
    ESEdge,
    StatementSchema,
    XrefSchema,
)

__all__ = [
    # Foundation
    "APIBaseModel",
    "DatedSchema",
    "SDict",
    "Status",
    "db",
    "make_token",
    "model_dump",
    # SQLAlchemy models
    "Alert",
    "Bookmark",
    "Collection",
    "Document",
    "Entity",
    "EntitySet",
    "EntitySetItem",
    "Event",
    "Events",
    "Export",
    "Judgement",
    "Mapping",
    "Permission",
    "Role",
    "Tag",
    # Pydantic resource schemas
    "AlertSchema",
    "BookmarkSchema",
    "CanonicalSchema",
    "CollectionDeepSchema",
    "CollectionJobStatus",
    "CollectionSchema",
    "CollectionStageStatus",
    "CollectionStatistics",
    "CollectionStatus",
    "DatasetDiscovery",
    "DiagramEdge",
    "DiagramGrouping",
    "DiagramLayout",
    "DiagramLayoutSettings",
    "DiagramVertex",
    "ESEdge",
    "EntityExpandSchema",
    "EntitySchema",
    "EntitySetItemSchema",
    "EntitySetSchema",
    "EntitySetType",
    "EntityTagSchema",
    "EventSchema",
    "ExportSchema",
    "FacetCounts",
    "MappingSchema",
    "MentionedTerms",
    "NotificationSchema",
    "PermissionSchema",
    "RoleSchema",
    "RoleType",
    "SignificantTerms",
    "SimilarSchema",
    "StatementSchema",
    "StatusCounts",
    "TagSchema",
    "Term",
    "XrefSchema",
]
