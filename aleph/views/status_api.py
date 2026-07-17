import logging

from flask import Blueprint, request

from aleph.logic.resolver import cache
from aleph.model import CollectionSchema
from aleph.procrastinate.status import get_active_collections_status
from aleph.views.serializers import CollectionSerializer
from aleph.views.util import jsonify, require

log = logging.getLogger(__name__)
blueprint = Blueprint("status_api", __name__)


@blueprint.route("/api/2/status", methods=["GET"])
def status():
    """
    ---
    get:
      summary: Get an overview of collections and exports being processed
      description: >
        List collections being processed currently and pending task counts
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SystemStatusResponse'
      tags:
      - System
    """
    require(request.authz.logged_in)
    request.rate_limit = None

    # if the current user can read the current collection, add it to the result
    statuses = [
        collection_status
        for collection_status in get_active_collections_status()
        if request.authz.can(collection_status.collection_id, request.authz.READ)
    ]

    # Embed the serialized collection on each result – the status UI renders
    # collection.label and gates its cancel button on collection.writeable.
    schemas = cache.get_many(CollectionSchema, [str(s.collection_id) for s in statuses])
    serializer = CollectionSerializer(nested=True)
    collections = {str(data["id"]): data for data in serializer.serialize_many(schemas)}

    results = []
    for collection_status in statuses:
        result = collection_status.model_dump(mode="json")
        result["collection"] = collections.get(str(collection_status.collection_id))
        results.append(result)

    return jsonify({"results": results, "total": len(results)})
