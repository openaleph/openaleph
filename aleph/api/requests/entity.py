"""Request body schemas for the entities endpoints."""

from pydantic import Field

from aleph.model.collection import CollectionSchema
from aleph.model.common import APIBaseModel, SDict


class EntityUpdate(APIBaseModel):
    """``PUT /api/2/entities/<id>`` body — partial update.

    ``schema`` is required; ``properties`` is the FTM property bag.
    The python attribute is named ``schema_`` because pydantic reserves
    ``schema`` for the model's own JSON-Schema method; the JSON wire
    name is ``schema``.
    """

    id: str | None = None
    collection_id: str | None = None
    schema_: str = Field(alias="schema")
    properties: SDict = {}


class EntityCreate(EntityUpdate):
    """``POST /api/2/entities`` body — extends ``EntityUpdate`` with the
    create-only ``foreign_id`` and the option to pass the parent
    collection inline rather than by id."""

    collection: CollectionSchema | None = None
    foreign_id: str | None = None
