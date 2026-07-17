"""Request body schemas for the entityset endpoints."""

from pydantic import Field

from aleph.model.common import APIBaseModel, SDict


class EntitySetCreate(APIBaseModel):
    """``POST /api/2/entitysets`` body."""

    label: str
    type: str
    collection_id: str
    summary: str | None = None
    layout: SDict | None = None
    entities: list[SDict] = []


class EntitySetUpdate(APIBaseModel):
    """``POST /api/2/entitysets/<id>`` body."""

    label: str | None = None
    summary: str | None = None
    type: str | None = None
    layout: SDict | None = None


class EntitySetItemUpdate(APIBaseModel):
    """``POST /api/2/entitysets/<id>/items`` body."""

    entity_id: str | None = None
    entity: SDict | None = None
    judgement: str | None = None
    compared_to_entity_id: str | None = None


class EntitySetEntityUpdate(APIBaseModel):
    """``POST /api/2/entitysets/<id>/entities`` body – upsert entity."""

    id: str | None = None
    schema_: str = Field(alias="schema")
    properties: SDict = {}
