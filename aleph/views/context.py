import math
import threading
import time
import uuid
from datetime import datetime

import structlog
from banal import hash_data
from flask import Blueprint, Response, request
from flask_babel import get_locale
from servicelayer.rate_limit import RateLimit
from structlog.contextvars import bind_contextvars, clear_contextvars
from werkzeug.exceptions import Forbidden, TooManyRequests, Unauthorized

from aleph import __version__
from aleph.authz import Authz
from aleph.core import kv
from aleph.model import Role
from aleph.scoped_tokens import burn_scoped_token, is_scoped_token
from aleph.settings import SETTINGS

log = structlog.get_logger(__name__)
local = threading.local()
blueprint = Blueprint("context", __name__)

# The complete list of endpoints a scoped token may call. Every other
# endpoint -- including any added in the future -- refuses a scoped token,
# whatever the owner of the token is allowed to do there. The list holds
# reading and writing *data* inside collections, each of which checks the
# collection through `Authz.can()` or `Authz.search_auth`. It deliberately
# leaves out everything about the account (roles, groups, sessions, tokens,
# alerts, notifications, bookmarks, tags, exports) and everything that
# administers a collection (create, update, delete, permissions, mappings,
# re-index, cross-reference runs).
SCOPED_TOKEN_ENDPOINTS = frozenset(
    (
        "base_api.metadata",
        "collections_api.index",
        "collections_api.view",
        "collections_api.bulk",
        "ingest_api.ingest_upload",
        "entities_api.index",
        "entities_api.match",
        "entities_api.create",
        "entities_api.view",
        "entities_api.similar",
        "entities_api.tags",
        "entities_api.update",
        "entities_api.delete",
        "entities_api.entitysets",
        "entitysets_api.index",
        "entitysets_api.create",
        "entitysets_api.view",
        "entitysets_api.update",
        "entitysets_api.delete",
        "entitysets_api.entities_index",
        "entitysets_api.entities_update",
        "entitysets_api.item_index",
        "entitysets_api.item_update",
        "xref_api.index",
        "bulk_api.entities",
        "archive_api.resolve",
        "archive_api.retrieve",
    )
)


class NotModified(Exception):
    """Converts to HTTP status 304."""

    pass


def handle_not_modified(exc):
    return Response(status=304)


def tag_request(**kwargs):
    """Store metadata for structured log output."""
    for tag, value in kwargs.items():
        if value is not None:
            request._log_tags[tag] = value


def enable_cache(vary_user=True, vary=None):
    """Enable caching in the context of a view.

    If desired, instructions on the cache parameters can be included, such as
    if the data is fit for public caches (default: no, vary_user) and what
    values to include in the generation of an etag.
    """
    if not SETTINGS.CACHE:
        return

    request._http_cache = True
    request._http_revalidate = vary is not None
    args = sorted(set(request.args.items()))
    cache_parts = [args, vary, request._app_locale]

    if vary_user and request.authz.logged_in:
        cache_parts.extend((request.authz.roles))
        if request.authz.scope is not None:
            # A scoped token has no roles to tell its responses apart.
            cache_parts.extend(("scoped", request.authz.scope.key_id))
        request._http_private = True

    request._http_etag = hash_data(cache_parts)
    if request._http_etag in request.if_none_match:
        raise NotModified()


def _get_remote_ip():
    forwarded_for = request.headers.getlist("X-Forwarded-For")
    if len(forwarded_for):
        return forwarded_for[0]
    return request.remote_addr


def _get_credential_authz(credential, allow_scoped=True):
    if credential is None or not len(credential):
        return
    if " " in credential:
        method, credential = credential.split(" ", 1)
        if method == "Token":
            return Authz.from_token(credential)

    if is_scoped_token(credential):
        # Never falls through to the API key lookup below.
        if not allow_scoped:
            burn_scoped_token(credential)
            raise Unauthorized()
        return Authz.from_scoped_token(credential)

    role = Role.by_api_key(credential)
    if role is not None:
        return Authz.from_role(role=role)


def get_authz(request):
    authz = None

    if "Authorization" in request.headers:
        credential = request.headers.get("Authorization")
        authz = _get_credential_authz(credential)

    if authz is None and "api_key" in request.args:
        # URLs end up in logs, browser histories and referrers: a scoped
        # token is only accepted in the `Authorization` header.
        authz = _get_credential_authz(request.args.get("api_key"), allow_scoped=False)

    return authz


def enable_authz(request):
    authz = get_authz(request)

    authz = authz or Authz.from_role(role=None)
    request.authz = authz


def enforce_scope(request):
    """Refuse a scoped token on every endpoint that is not allowlisted."""
    if request.authz.scope is None:
        return
    if request.endpoint not in SCOPED_TOKEN_ENDPOINTS:
        raise Forbidden()


def get_rate_limit(resource, limit=100, interval=60, unit=1):
    return RateLimit(kv, resource, limit=limit, interval=interval, unit=unit)


def enable_rate_limit(request):
    if request.authz.logged_in:
        return
    limit = SETTINGS.API_RATE_LIMIT * SETTINGS.API_RATE_WINDOW
    request.rate_limit = get_rate_limit(
        _get_remote_ip(), limit=limit, interval=SETTINGS.API_RATE_WINDOW, unit=60
    )
    if not request.rate_limit.check():
        raise TooManyRequests("Rate limit exceeded.")


@blueprint.before_app_request
def setup_request():
    """Set some request attributes at the beginning of the request.
    By default, caching will be disabled."""
    request._begin_time = time.time()
    request._app_locale = str(get_locale())
    request._session_id = request.headers.get("X-Aleph-Session")
    request._http_cache = False
    request._http_private = False
    request._http_revalidate = False
    request._http_etag = None
    request._log_tags = {}
    request._trace_id = str(uuid.uuid4())

    # First set up auth context so that we know who we are dealing with
    # when we log their activity or enforce rate limits
    enable_authz(request)
    setup_logging_context(request)
    enforce_scope(request)
    enable_rate_limit(request)


@blueprint.after_app_request
def finalize_response(resp):
    """Post-request processing to set cache parameters."""
    # Compute overall request duration:
    now = time.time()
    took = now - getattr(request, "_begin_time", now)

    # Finalize reporting of the rate limiter:
    if hasattr(request, "rate_limit") and request.rate_limit is not None:
        usage = request.rate_limit.update(amount=math.ceil(took))
        resp.headers["X-Rate-Limit"] = request.rate_limit.limit
        resp.headers["X-Rate-Usage"] = usage

    generate_request_log(resp, took)
    if resp.is_streamed:
        # http://wiki.nginx.org/X-accel#X-Accel-Buffering
        resp.headers["X-Accel-Buffering"] = "no"

    if not hasattr(request, "_http_cache") or not request._http_cache:
        resp.cache_control.no_cache = True
        return resp

    if request.method != "GET" or resp.status_code != 200:
        resp.cache_control.no_cache = True
        return resp

    resp.cache_control.public = True
    resp.vary.add("Accept-Language")
    resp.vary.add("Authorization")

    if request._http_etag:
        resp.set_etag(request._http_etag)
        if request._http_revalidate:
            resp.cache_control.must_revalidate = request._http_revalidate
        else:
            resp.cache_control.max_age = 3600 * 12
    else:
        resp.expires = -1

    if request._http_private:
        resp.cache_control.public = None
        resp.cache_control.private = True
    return resp


def setup_logging_context(request):
    role_id = None
    scoped_token_id = None
    if hasattr(request, "authz"):
        role_id = request.authz.id
        if request.authz.scope is not None:
            scoped_token_id = request.authz.scope.key_id
    # Set up context variables for structured logging. The context is included
    # with every log entry produced by this particular request
    clear_contextvars()
    bind_contextvars(
        v=__version__,
        method=request.method,
        endpoint=request.endpoint,
        referrer=request.referrer,
        ip=_get_remote_ip(),
        ua=str(request.user_agent),
        begin_time=datetime.utcfromtimestamp(request._begin_time).isoformat(),
        role_id=role_id,
        scoped_token_id=scoped_token_id,
        session_id=getattr(request, "_session_id", None),
        locale=getattr(request, "_app_locale", None),
        url=request.url,
        path=request.full_path,
        trace_id=request._trace_id,
    )


def generate_request_log(resp, took):
    """Collect data about the request for analytical purposes."""
    # Only add the context info that hasn't been already set in the beginning
    # of the request
    payload = {
        "time": datetime.utcnow().isoformat(),
        "took": took,
        "status": resp.status_code,
    }
    tags = dict(request.view_args or ())
    if hasattr(request, "_log_tags"):
        tags.update(request._log_tags)
    for tag, value in tags.items():
        if value is not None and tag not in payload:
            payload[tag] = value
    bind_contextvars(**payload)
    # This logging statement is here to make sure we log the context of every
    # request for analytics purposes
    log.info("Request handled", request_logging=True)
