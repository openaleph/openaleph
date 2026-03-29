import logging

from flask import Blueprint, request
from werkzeug.exceptions import NotFound

from aleph.core import db
from aleph.model import Export
from aleph.search import DatabaseQueryResult
from aleph.views.serializers import ExportSerializer
from aleph.views.util import require

log = logging.getLogger(__name__)
blueprint = Blueprint("exports_api", __name__)


@blueprint.route("/api/2/exports", methods=["GET"])
def index():
    """Returns a list of exports for the user.
    ---
    get:
      summary: List exports
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                allOf:
                - $ref: '#/components/schemas/QueryResponse'
                properties:
                  results:
                    type: array
                    items:
                      $ref: '#/components/schemas/Export'
          description: OK
      tags:
        - Export
    """
    require(request.authz.logged_in)
    query = Export.by_role_id(request.authz.id)
    result = DatabaseQueryResult(request, query)
    return ExportSerializer.jsonify_result(result)


@blueprint.route("/api/2/exports/<int:export_id>", methods=["DELETE"])
def delete(export_id):
    """Delete an export.
    ---
    delete:
      summary: Delete an export
      parameters:
      - in: path
        name: export_id
        required: true
        schema:
          type: integer
        description: Export ID
      responses:
        '204':
          description: Export deleted successfully
        '404':
          description: Export not found
      tags:
        - Export
    """
    require(request.authz.logged_in)
    export = Export.by_id(export_id, role_id=request.authz.id)
    if export is None:
        raise NotFound("Export not found")
    
    export.deleted = True
    db.session.add(export)
    db.session.commit()
    return ("", 204)
