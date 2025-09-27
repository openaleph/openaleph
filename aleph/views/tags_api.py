import logging
from typing import Any

from flask import Blueprint, request
from sqlalchemy import func
from werkzeug.exceptions import BadRequest, Forbidden, NotFound

from aleph.authz import Authz
from aleph.core import db
from aleph.logic import collections
from aleph.logic.aggregator import get_aggregator
from aleph.model.collection import Collection
from aleph.model.tag import Tag
from aleph.search import DatabaseQueryResult
from aleph.views.serializers import TagSerializer
from aleph.views.util import get_index_entity, jsonify, parse_request, require

log = logging.getLogger(__name__)
blueprint = Blueprint("tags_api", __name__)


def require_entity_taggable(entity_id: str, authz: Authz) -> dict[str, Any]:
    try:
        entity = get_index_entity(entity_id, authz.READ)
        collection = Collection.by_id(entity["collection_id"])
        if not collection or not collection.taggable:
            raise Forbidden
        return entity
    except (NotFound, Forbidden):
        raise BadRequest(
            "Could not tag the given entity as the entity does not exist or "
            "you do not have access or tagging is disabled."
        )


def reindex_entity(entity_id: str, collection: Collection) -> None:
    """Re-index a single entity to update its tags in the search index."""
    aggregator = get_aggregator(collection)
    collections.index_aggregator(collection, aggregator, entity_ids=[entity_id])


@blueprint.route("/api/2/tags", methods=["GET"])
def index():
    """Get a list of tags for a given collection, ordered by occurrence count
    ---
    get:
      summary: Get tags
      tags: [Tags]
      parameters:
        - in: query
          name: limit
          description: Number of tags to return
          schema:
            type: number
        - in: query
          name: offset
          description: Number of tags to skip
        - in: query
          name: entity_id
          description: Filter tags by entity ID
          schema:
            type: string
        - in: query
          name: collection_id
          description: Collection ID to get tags for
          required: true
          schema:
            type: number
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TagsResponse'
    """
    authz = request.authz
    require(authz.logged_in)

    collection_id = request.args.get("collection_id")
    if not collection_id:
        raise BadRequest("collection_id parameter is required")

    collection_id = int(collection_id)
    require(authz.can(collection_id, authz.READ))
    collection = Collection.by_id(collection_id)
    if not collection or not collection.taggable:
        raise BadRequest("Tagging is disabled")

    # Base query for tags in the collection
    query = Tag.query.filter(Tag.collection_id == collection_id)

    # Optional entity filter
    entity_id = request.args.get("entity_id")
    if entity_id:
        require_entity_taggable(entity_id, authz)
        query = query.filter(Tag.entity_id == entity_id)
        # If filtering by entity, order by creation date
        query = query.order_by(Tag.created_at.desc())
    else:
        # Group by tag value and order by occurrence count
        query = (
            db.session.query(Tag.tag, func.count(Tag.entity_id).label("count"))
            .filter(Tag.collection_id == collection_id)
            .group_by(Tag.tag)
            .order_by(func.count(Tag.entity_id).desc(), Tag.tag)
        )

    result = DatabaseQueryResult(request, query)
    return TagSerializer.jsonify_result(result)


@blueprint.route("/api/2/tags", methods=["POST"])
def create():
    """Create a tag for an entity.
    ---
    post:
      summary: Create tag
      tags: [Tags]
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/TagCreate'
      responses:
        '201':
          description: Created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Tag'
        '400':
          description: Bad request
    """
    require(request.authz.session_write)
    data = parse_request("TagCreate")
    entity_id = data.get("entity_id")
    tag_text = data.get("tag")

    if not tag_text:
        raise BadRequest("Tag text is required")
    if not entity_id:
        raise BadRequest("Entity ID is required")

    entity = require_entity_taggable(entity_id, request.authz)

    # Check if tag already exists for this entity and user
    existing_tag = Tag.query.filter_by(
        entity_id=entity_id, role_id=request.authz.id, tag=tag_text
    ).first()

    if existing_tag:
        serializer = TagSerializer()
        response = serializer.serialize(existing_tag)
        return jsonify(response, status=200)

    tag = Tag(
        entity_id=entity_id,
        collection_id=int(entity.get("collection_id")),
        role_id=request.authz.id,
        tag=tag_text,
    )

    db.session.add(tag)
    db.session.commit()

    # Re-index the entity to update tags in search index
    collection = Collection.by_id(tag.collection_id)
    reindex_entity(entity_id, collection)

    serializer = TagSerializer()
    response = serializer.serialize(tag)
    return jsonify(response, status=201)


@blueprint.route("/api/2/tags/<entity_id>", methods=["GET"])
def get_by_entity(entity_id):
    """Get all tags for a specific entity.
    ---
    get:
      summary: Get tags for entity
      tags: [Tags]
      parameters:
        - in: path
          name: entity_id
          description: ID of the entity
          required: true
          schema:
            type: string
        - in: query
          name: limit
          description: Number of tags to return
          schema:
            type: number
        - in: query
          name: offset
          description: Number of tags to skip
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TagsResponse'
    """
    require_entity_taggable(entity_id, request.authz)

    # Get all tags for this entity
    query = Tag.query.filter(Tag.entity_id == entity_id).order_by(Tag.created_at.desc())
    result = DatabaseQueryResult(request, query)
    return TagSerializer.jsonify_result(result)


@blueprint.route("/api/2/tags/<entity_id>/<tag>", methods=["DELETE"])
def delete(entity_id, tag):
    """Delete all tags with the specified entity_id and tag value.
    ---
    delete:
      summary: Delete tag by entity and tag value
      tags: [Tags]
      parameters:
        - in: path
          name: entity_id
          description: ID of the entity
          required: true
          schema:
            type: string
        - in: path
          name: tag
          description: Tag value to delete
          required: true
          schema:
            type: string
      responses:
        '204':
          description: No content
    """
    require(request.authz.session_write)
    entity = require_entity_taggable(entity_id, request.authz)

    query = Tag.query.filter_by(entity_id=entity_id, tag=tag)
    query.delete()
    db.session.commit()

    # Re-index the entity to update tags in search index
    collection = Collection.by_id(entity["collection_id"])
    reindex_entity(entity_id, collection)

    return "", 204


@blueprint.route("/api/2/tags/<entity_id>", methods=["DELETE"])
def delete_by_entity(entity_id):
    """Delete all tags for an entity.
    ---
    delete:
      summary: Delete all tags for entity
      tags: [Tags]
      parameters:
        - in: path
          name: entity_id
          description: ID of the entity
          required: true
          schema:
            type: string
      responses:
        '204':
          description: No content
    """
    require(request.authz.session_write)
    entity = require_entity_taggable(entity_id, request.authz)

    query = Tag.query.filter_by(entity_id=entity_id)
    query.delete()
    db.session.commit()

    # Re-index the entity to update tags in search index
    collection = Collection.by_id(entity["collection_id"])
    reindex_entity(entity_id, collection)

    return "", 204
