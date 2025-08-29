from flask import Blueprint, request

from aleph.search import NotificationsQuery
from aleph.search.result import get_query_result
from aleph.views.serializers import NotificationSerializer
from aleph.views.util import require

blueprint = Blueprint("notifications_api", __name__)


@blueprint.route("/api/2/notifications", methods=["GET"])
def index():
    """
    ---
    get:
      summary: Get notifications
      description: Get all the notifications for the user
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
                      $ref: '#/components/schemas/Notification'
          description: OK
      tags:
      - Notification
    """
    require(request.authz.logged_in)
    result = get_query_result(NotificationsQuery, request)
    return NotificationSerializer.jsonify_result(result)
