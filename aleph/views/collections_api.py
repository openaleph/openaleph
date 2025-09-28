from banal import ensure_list
from flask import Blueprint, request
from werkzeug.exceptions import BadRequest

from aleph.core import db
from aleph.index.collections import update_collection_stats
from aleph.logic.collections import (
    create_collection,
    delete_collection,
    get_deep_collection,
    refresh_collection,
    reingest_collection,
    update_collection,
)
from aleph.logic.discover import get_collection_discovery
from aleph.logic.entitysets import save_entityset_item
from aleph.logic.processing import bulk_write
from aleph.procrastinate.queues import (
    queue_cancel_collection,
    queue_index,
    queue_reindex,
)
from aleph.procrastinate.status import get_collection_status
from aleph.search import CollectionsQuery
from aleph.search.result import get_query_result
from aleph.views.serializers import CollectionSerializer
from aleph.views.util import (
    get_db_collection,
    get_entityset,
    get_flag,
    get_index_collection,
    get_session_id,
    jsonify,
    parse_request,
    require,
)

blueprint = Blueprint("collections_api", __name__)


@blueprint.route("", methods=["GET"])
def index():
    """
    ---
    get:
      summary: List collections
      description: >-
        Returns a list of collections matching a given query. Returns all the
        collections accessible by a user if no query is given.
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CollectionsResponse'
      tags:
      - Collection
    """
    require(request.authz.can_browse_anonymous)
    result = get_query_result(CollectionsQuery, request)
    return CollectionSerializer.jsonify_result(result)


@blueprint.route("", methods=["POST", "PUT"])
def create():
    """
    ---
    post:
      summary: Create a collection
      description: Create a collection with the given metadata
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CollectionCreate'
      tags:
        - Collection
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Collection'
    """
    require(request.authz.session_write)
    data = parse_request("CollectionCreate")
    sync = get_flag("sync", True)
    try:
        collection = create_collection(data, request.authz, sync=sync)
    except ValueError:
        raise BadRequest()
    return view(collection.get("id"))


@blueprint.route("/<int:collection_id>", methods=["GET"])
def view(collection_id):
    """
    ---
    get:
      summary: Get a collection
      description: Return the collection with id `collection_id`
      parameters:
      - description: The collection ID.
        in: path
        name: collection_id
        required: true
        schema:
          minimum: 1
          type: integer
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CollectionDeep'
      tags:
      - Collection
    """
    require(request.authz.can_browse_anonymous)
    data = get_index_collection(collection_id)
    cobj = get_db_collection(collection_id)
    if get_flag("refresh", False):
        update_collection_stats(collection_id, ["schema"])
    data.update(get_deep_collection(cobj))
    return CollectionSerializer.jsonify(data)


@blueprint.route("/<int:collection_id>", methods=["POST", "PUT"])
def update(collection_id):
    """
    ---
    post:
      summary: Update a collection
      description: >
        Change collection metadata and update statistics.
      parameters:
      - description: The collection ID.
        in: path
        name: collection_id
        required: true
        schema:
          minimum: 1
          type: integer
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CollectionUpdate'
      tags:
        - Collection
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Collection'
    """
    collection = get_db_collection(collection_id, request.authz.WRITE)
    data = parse_request("CollectionUpdate")
    sync = get_flag("sync")
    collection.update(data, request.authz)
    db.session.commit()
    data = update_collection(collection, sync=sync)
    return CollectionSerializer.jsonify(data)


@blueprint.route("/<int:collection_id>/reingest", methods=["POST", "PUT"])
def reingest(collection_id):
    """
    ---
    post:
      summary: Re-ingest a collection
      description: >
        Trigger a process to re-parse the content of all documents stored
        in the collection with id `collection_id`.
      parameters:
      - description: The collection ID.
        in: path
        name: collection_id
        required: true
        schema:
          minimum: 1
          type: integer
      - in: query
        name: index
        description: Index documents while they're being processed.
        schema:
          type: boolean
      responses:
        '202':
          description: Accepted
      tags:
      - Collection
    """
    collection = get_db_collection(collection_id, request.authz.WRITE)
    index = get_flag("index", False)
    reingest_collection(collection, job_id=get_session_id(), index=index)
    return ("", 202)


@blueprint.route("/<int:collection_id>/reindex", methods=["POST", "PUT"])
def reindex(collection_id):
    """
    ---
    post:
      summary: Re-index a collection
      description: >
        Re-index the entities in the collection with id `collection_id`
      parameters:
      - description: The collection ID.
        in: path
        name: collection_id
        required: true
        schema:
          minimum: 1
          type: integer
      - in: query
        description: Delete the index before re-generating it.
        name: flush
        schema:
          type: boolean
      responses:
        '202':
          description: Accepted
      tags:
      - Collection
    """
    collection = get_db_collection(collection_id, request.authz.WRITE)
    queue_reindex(collection, flush=get_flag("flush", False))
    return ("", 202)


@blueprint.route("/<int:collection_id>/_bulk", methods=["POST"])
@blueprint.route("/<int:collection_id>/bulk", methods=["POST"])
def bulk(collection_id):
    """
    ---
    post:
      summary: Load entities into a collection
      description: >
        Bulk load entities into the collection with id `collection_id`
      parameters:
      - description: The collection ID.
        in: path
        name: collection_id
        required: true
        schema:
          minimum: 1
          type: integer
      - description: >-
          safe=True means that the data cannot be trusted
          and that file checksums should be removed.
          Flag is only available for admins. Default True.
        in: query
        name: safe
        schema:
          type: boolean
      - description: >-
          clean=True means that the data cannot be trusted
          and that the data should be cleaned from invalid values.
          Flag is only available for admins. Default True.
        in: query
        name: clean
        schema:
          type: boolean
      requestBody:
        description: Entities to be loaded.
        content:
          application/json:
            schema:
              type: array
              items:
                $ref: '#/components/schemas/EntityUpdate'
      responses:
        '204':
          description: No Content
      tags:
      - Collection
    """
    collection = get_db_collection(collection_id, request.authz.WRITE)
    require(request.authz.can_bulk_import())
    entityset = request.args.get("entityset_id")
    if entityset is not None:
        entityset = get_entityset(entityset, request.authz.WRITE)

    # This will disable (if False) checksum security measures in order to allow bulk
    # loading of document data:
    safe = get_flag("safe", default=True)
    # Flag is only available for admins:
    if not request.authz.is_admin:
        safe = True

    # This will disable (if False) values validation for all types of all entities / properties
    # (will pass cleaned=True to the model.get_proxy() in the aleph/logic/processing.py)
    clean = get_flag("clean", default=True)
    # Flag is only available for admins:
    if not request.authz.is_admin:
        clean = True

    # Let UI tools change the entities created by this:
    mutable = get_flag("mutable", default=False)
    entities_data = ensure_list(request.get_json(force=True))
    entities = list()
    for entity in bulk_write(
        collection,
        entities_data,
        safe=safe,
        mutable=mutable,
        clean=clean,
        role_id=request.authz.id,
    ):
        entities.append(entity)
        if entityset is not None:
            save_entityset_item(
                entityset,
                collection,
                entity.id,
                added_by_id=request.authz.id,
            )
    collection.touch()
    db.session.commit()
    queue_index(collection, entities)
    return ("", 204)


@blueprint.route("/<int:collection_id>/status", methods=["GET"])
def status(collection_id):
    """
    ---
    get:
      summary: Check processing status of a collection
      description: >
        Return the task queue status for the collection with id `collection_id`
      parameters:
      - description: The collection ID.
        in: path
        name: collection_id
        required: true
        schema:
          minimum: 1
          type: integer
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CollectionStatus'
      tags:
      - Collection
    """
    collection = get_db_collection(collection_id, request.authz.READ)
    request.rate_limit = None
    status = get_collection_status(collection)
    return jsonify(status.model_dump(mode="json"))


@blueprint.route("/<int:collection_id>/status", methods=["DELETE"])
def cancel(collection_id):
    """
    ---
    delete:
      summary: Cancel processing of a collection
      description: >
        Cancel all queued tasks for the collection with id `collection_id`
      parameters:
      - description: The collection ID.
        in: path
        name: collection_id
        required: true
        schema:
          minimum: 1
          type: integer
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CollectionStatus'
          description: OK
      tags:
      - Collection
    """
    collection = get_db_collection(collection_id, request.authz.WRITE)
    queue_cancel_collection(collection)
    refresh_collection(collection_id)
    return ("", 204)


@blueprint.route("/<int:collection_id>/discover", methods=["GET"])
def discover(collection_id):
    """
    ---
    get:
      summary: Get dataset discovery analysis for a collection
      description: >
        Return cached dataset discovery analysis with significant terms and mentioned entities
        for the collection with id `collection_id`
      parameters:
      - description: The collection ID.
        in: path
        name: collection_id
        required: true
        schema:
          minimum: 1
          type: integer
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/DatasetDiscovery'
      tags:
      - Collection
    """
    collection = get_db_collection(collection_id, request.authz.READ)

    # Return cached discovery analysis
    discovery = get_collection_discovery(collection_id, collection.foreign_id)
    return jsonify(discovery.model_dump(mode="json"))


@blueprint.route("/<int:collection_id>", methods=["DELETE"])
def delete(collection_id):
    """
    ---
    delete:
      summary: Delete a collection
      description: Delete the collection with id `collection_id`
      parameters:
      - description: The collection ID.
        in: path
        name: collection_id
        required: true
        schema:
          minimum: 1
          type: integer
      - in: query
        description: Wait for delete to finish in backend.
        name: sync
        schema:
          type: boolean
      - in: query
        description: Delete only the contents, but not the collection itself.
        name: keep_metadata
        schema:
          type: boolean
      responses:
        '204':
          description: No Content
      tags:
        - Collection
    """
    collection = get_db_collection(collection_id, request.authz.WRITE)
    keep_metadata = get_flag("keep_metadata", default=False)
    sync = get_flag("sync", default=True)
    delete_collection(collection, keep_metadata=keep_metadata, sync=sync)
    return ("", 204)
