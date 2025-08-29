import logging
from datetime import datetime

from banal import hash_data
from followthemoney.util import get_entity_id
from openaleph_search.index.indexer import configure_index, index_safe, query_delete
from openaleph_search.index.mapping import FieldType
from openaleph_search.index.util import index_name, index_settings

log = logging.getLogger(__name__)


def notifications_index():
    return index_name("notifications", "v1")


def configure_notifications():
    mapping = {
        "date_detection": False,
        "dynamic": False,
        "properties": {
            "event": FieldType.KEYWORD,
            "actor_id": FieldType.KEYWORD,
            "channels": FieldType.KEYWORD,
            "created_at": {"type": "date"},
            "params": {"dynamic": True, "type": "object"},
        },
    }
    index = notifications_index()
    settings = index_settings(shards=3)
    return configure_index(index, mapping, settings)


def index_notification(event, actor_id, params, channels, sync=False):
    """Index a notification."""
    params = params or {}
    data = {}
    for param, value in params.items():
        value = get_entity_id(value)
        if value is not None:
            data[param] = str(value)
    channels = list(set([c for c in channels if c is not None]))
    data = {
        "actor_id": actor_id,
        "params": data,
        "event": event.name,
        "channels": channels,
        "created_at": datetime.utcnow(),
    }
    index = notifications_index()
    id_ = hash_data((actor_id, event.name, channels, params))
    return index_safe(index, id_, data, sync=sync)


def delete_notifications(filter_, sync=False):
    """Delete notifications from a specific channel."""
    query = {"bool": {"filter": [filter_]}}
    query_delete(notifications_index(), query, sync=sync)
