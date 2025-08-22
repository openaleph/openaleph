import logging

from flask import Blueprint, request

from aleph.procrastinate.status import get_active_collections_status
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

    results = []
    for collection_status in get_active_collections_status():
        # if the current user can read the current collection, add it to the result
        if request.authz.can(collection_status.collection_id, request.authz.READ):
            results.append(collection_status.model_dump(mode="json"))

    return jsonify({"results": results, "total": len(results)})
