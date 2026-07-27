import logging
from datetime import datetime, timedelta

from banal import ensure_list
from flask import render_template
from followthemoney.util import get_entity_id
from openaleph_search.index.util import unpack_result

from aleph.authz import Authz
from aleph.core import es
from aleph.index.notifications import (
    delete_notifications,
    index_notification,
    notifications_index,
)
from aleph.logic.html import html_link
from aleph.logic.mail import email_role
from aleph.logic.resolver import cache
from aleph.logic.resolver.registry import register
from aleph.logic.resolver.ttl import TTL_RESOURCE
from aleph.logic.util import (
    archive_url,
    collection_url,
    entity_url,
    entityset_url,
    ui_url,
)
from aleph.model import (
    AlertSchema,
    Collection,
    CollectionSchema,
    EntitySchema,
    EntitySetSchema,
    Events,
    EventSchema,
    ExportSchema,
    Role,
    RoleSchema,
)
from aleph.model.role import RoleChannels
from aleph.settings import SETTINGS

log = logging.getLogger(__name__)
GLOBAL = "Global"


def channel_tag(obj, clazz=None):
    clazz = clazz or type(obj)
    if clazz is str:
        return obj

    obj = get_entity_id(obj)
    if obj is not None:
        return "%s:%s" % (clazz.__name__, obj)


def publish(event: EventSchema, actor_id=None, params=None, channels=None):
    """Publish a notification to the given channels, while storing
    the parameters and initiating actor for the event."""
    channels = [channel_tag(c) for c in ensure_list(channels)]
    index_notification(event, actor_id, params, channels)


def delete_old_notifications(sync=False):
    """Delete out-dated notifications from the index."""
    cutoff = datetime.utcnow() - SETTINGS.NOTIFICATIONS_DELETE
    filter_ = {"range": {"created_at": {"lt": cutoff}}}
    log.debug("Deleting old notifications before: %r", cutoff)
    delete_notifications(filter_, sync=sync)


def flush_notifications(obj, clazz=None, sync=False):
    """Delete all notifications in a given channel."""
    filter_ = {"term": {"channels": channel_tag(obj, clazz=clazz)}}
    delete_notifications(filter_, sync=sync)


def get_role_channels(role_id: str | None) -> list[str]:
    """Get notification channels for a role via the resolver.

    Accepts a role_id string (or None for anonymous).
    """
    if role_id is None:
        return [GLOBAL]
    role_channels = cache.get(RoleChannels, str(role_id))
    if role_channels is not None:
        return role_channels.channels
    return [GLOBAL]


@register(RoleChannels, ttl=TTL_RESOURCE)
def _fetch_role_channels(role_id: str) -> RoleChannels | None:
    """Compute notification channels for a role."""
    role = Role.by_id(int(role_id))
    if role is None:
        return None
    channels = [GLOBAL]
    if role.is_actor:
        authz = Authz.from_role(role)
        for auth_role_id in authz.roles:
            channels.append(channel_tag(auth_role_id, Role))
        for coll_id in authz.collections(authz.READ):
            channels.append(channel_tag(coll_id, Collection))
    return RoleChannels(role_id=str(role_id), channels=channels)


def get_notifications(role: Role, since=None):
    """Fetch a stream of notifications for the given role."""
    channels = get_role_channels(str(role.id))
    filters = [{"terms": {"channels": channels}}]
    if since is not None:
        filters.append({"range": {"created_at": {"gt": since}}})
    must_not = [{"term": {"actor_id": role.id}}]
    query = {
        "size": 30,
        "query": {"bool": {"filter": filters, "must_not": must_not}},
        "sort": [{"created_at": {"order": "desc"}}],
    }
    return es.search(index=notifications_index(), body=query)


def _iter_params(data, event):
    if data.get("actor_id") is not None:
        yield "actor", RoleSchema, data.get("actor_id")
    params = data.get("params", {})
    for name, schema_cls in event.param_types.items():
        value = params.get(name)
        if value is not None:
            yield name, schema_cls, value


def render_notification(stub, notification):
    """Generate a text version of the notification, suitable for use
    in an email or text message."""
    from aleph.model.common import model_dump

    notification = unpack_result(notification)
    event = Events.get(notification.get("event"))
    if event is None:
        return

    # Batch pre-fetch all params via the resolver.
    for _, schema_cls, value in _iter_params(notification, event):
        cache.get(schema_cls, str(value))

    plain = str(event.template)
    html = str(event.template)
    for name, schema_cls, value in _iter_params(notification, event):
        obj = cache.get(schema_cls, str(value))
        if obj is None:
            return
        data = model_dump(obj) or {}
        link, title = None, None
        if schema_cls == RoleSchema:
            title = data.get("label")
        elif schema_cls == AlertSchema:
            title = data.get("query")
        elif schema_cls == CollectionSchema:
            title = data.get("title") or data.get("label")
            link = collection_url(value)
        elif schema_cls == EntitySchema:
            title = obj.caption
            link = entity_url(value)
        elif schema_cls == EntitySetSchema:
            title = data.get("label")
            link = entityset_url(data.get("id"))
        elif schema_cls == ExportSchema:
            title = data.get("label")
            link = archive_url(
                data.get("content_hash"),
                file_name=data.get("file_name"),
                mime_type=data.get("file_name"),
            )

        template = "{{%s}}" % name
        html = html.replace(template, html_link(title, link))
        plain = plain.replace(template, "'%s'" % title)
        if name == event.link_to:
            plain = "%s (%s)" % (plain, link)
    return {"plain": plain, "html": html}


def generate_digest():
    """Generate notification digest emails for all users."""
    for role in Role.all_users():
        if role.is_alertable:
            generate_role_digest(role)


def generate_role_digest(role):
    """Generate notification digest emails for the given user."""
    # TODO: get and use the role's locale preference.
    since = datetime.utcnow() - timedelta(hours=26)
    result = get_notifications(role, since=since)
    hits = result.get("hits", {})
    total_count = hits.get("total", {}).get("value")
    log.info("Daily digest: %r (%s notifications)", role, total_count)
    if total_count == 0:
        return
    notifications = [render_notification(role, n) for n in hits.get("hits")]
    notifications = [n for n in notifications if n is not None]
    params = dict(
        notifications=notifications,
        role=role,
        total_count=total_count,
        manage_url=ui_url("notifications"),
        ui_url=SETTINGS.APP_UI_URL,
        app_title=SETTINGS.APP_TITLE,
    )
    plain = render_template("email/notifications.txt", **params)
    html = render_template("email/notifications.html", **params)
    log.info("Notification: %s", plain)
    subject = "%s notifications" % total_count
    email_role(role, subject, html=html, plain=plain)
