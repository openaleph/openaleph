import logging
from datetime import datetime
from functools import lru_cache

from babel import Locale
from banal import as_bool
from elasticsearch import TransportError
from flask import Blueprint, current_app, request
from flask_babel import get_locale, gettext
from followthemoney import __version__ as ftm_version
from followthemoney import model
from followthemoney.exc import InvalidData
from jwt import DecodeError, ExpiredSignatureError
from rigour.langs import iso_639_alpha3
from werkzeug.exceptions import Unauthorized

from aleph import __version__
from aleph.authz import Authz
from aleph.core import archive, cache, get_cache, url_for
from aleph.logic.pages import load_pages
from aleph.logic.util import collection_url
from aleph.model import Collection, Role
from aleph.settings import SETTINGS
from aleph.validation import get_openapi_spec
from aleph.views.context import NotModified, enable_cache
from aleph.views.util import jsonify, render_xml

blueprint = Blueprint("base_api", __name__)
log = logging.getLogger(__name__)


@lru_cache(maxsize=None)
def _metadata_locale(locale):
    # This is cached in part because latency on this endpoint is
    # particularly relevant to the first render being shown to a
    # user.
    auth = {"oauth": SETTINGS.OAUTH, "require_logged_in": SETTINGS.REQUIRE_LOGGED_IN}
    if SETTINGS.PASSWORD_LOGIN:
        auth["password_login_uri"] = url_for("sessions_api.password_login")
    if SETTINGS.PASSWORD_LOGIN and not SETTINGS.MAINTENANCE:
        auth["registration_uri"] = url_for("roles_api.create_code")
    if SETTINGS.OAUTH:
        auth["oauth_uri"] = url_for("sessions_api.oauth_init")
    locales = SETTINGS.UI_LANGUAGES
    locales = {loc: Locale(loc).get_language_name(loc) for loc in locales}

    translate_source_languages = [
        iso_639_alpha3(lang) for lang in SETTINGS.FTM_TRANSLATE_SOURCE_LANGUAGES
    ]

    # This is dumb but we agreed it with ARIJ
    # https://github.com/alephdata/aleph/issues/1432
    app_logo = SETTINGS.APP_LOGO
    if locale.language.startswith("ar"):
        app_logo = SETTINGS.APP_LOGO_AR or app_logo

    return {
        "status": "ok",
        "maintenance": SETTINGS.MAINTENANCE,
        "app": {
            "title": SETTINGS.APP_TITLE,
            "version": __version__,
            "ftm_version": ftm_version,
            "banner": SETTINGS.APP_BANNER,
            "entity_banner_rules": SETTINGS.ENTITY_BANNER_RULES,
            "ui_uri": SETTINGS.APP_UI_URL,
            "messages_url": SETTINGS.APP_MESSAGES_URL,
            "publish": archive.can_publish,
            "logo": app_logo,
            "favicon": SETTINGS.APP_FAVICON,
            "locale": str(locale),
            "locales": locales,
        },
        "categories": Collection.CATEGORIES,
        "frequencies": Collection.FREQUENCIES,
        "pages": load_pages(locale),
        "model": model.to_dict(),
        "token": None,
        "auth": auth,
        "feature_flags": {
            "bookmarks": as_bool(SETTINGS.ENABLE_EXPERIMENTAL_BOOKMARKS_FEATURE),
            "timelines": as_bool(SETTINGS.ENABLE_TIMELINES),
            "lists": as_bool(SETTINGS.ENABLE_LISTS),
            "diagrams": as_bool(SETTINGS.ENABLE_NETWORK_DIAGRAMS),
        },
        "feedback_urls": {
            "documents": SETTINGS.FEEDBACK_URL_DOCUMENTS,
            "timelines": SETTINGS.FEEDBACK_URL_TIMELINES,
        },
        "service_urls": {"ftm_assets": SETTINGS.FTM_ASSETS_URL},
        "services": {"translate": {"source_languages": translate_source_languages}},
    }


@blueprint.route("/api/2/metadata")
def metadata():
    """Get operational metadata for the frontend.
    ---
    get:
      summary: Retrieve system metadata from the application.
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                type: object
      tags:
      - System
    """
    request.rate_limit = None
    locale = get_locale()
    data = _metadata_locale(locale)
    if SETTINGS.SINGLE_USER:
        role = Role.load_cli_user()
        authz = Authz.from_role(role)
        data["token"] = authz.to_token()
    return jsonify(data)


@blueprint.route("/api/openapi.json")
def openapi():
    """Generate an OpenAPI 3.0 documentation JSON file for the API."""
    enable_cache(vary_user=False)
    spec = get_openapi_spec(current_app)
    for name, view in current_app.view_functions.items():
        if name in (
            "static",
            "base_api.openapi",
            "base_api.api_v1_message",
            "sessions_api.oauth_callback",
        ):
            continue
        log.info("%s - %s", name, view.__qualname__)
        spec.path(view=view)
    return jsonify(spec.to_dict())


@blueprint.route("/api/2/statistics")
def statistics():
    """Get a summary of the data accessible to an anonymous user.

    Changed [3.9]: Previously, this would return user-specific stats.
    ---
    get:
      summary: System-wide user statistics.
      description: >
        Get a summary of the data accessible to an anonymous user.
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                type: object
      tags:
      - System
    """
    enable_cache(vary_user=False)
    key = cache.key(cache.STATISTICS)
    data = {"countries": [], "schemata": [], "categories": []}
    data = cache.get_complex(key) or data
    return jsonify(data)


@blueprint.route("/api/2/sitemap.xml")
def sitemap():
    """
    ---
    get:
      summary: Get a sitemap
      description: >-
        Returns a site map for search engine robots. This lists each
        published collection on the current instance.
      responses:
        '200':
          description: OK
          content:
            text/xml:
              schema:
                type: object
      tags:
      - System
    """
    enable_cache(vary_user=False)
    request.rate_limit = None
    collections = []
    for collection in Collection.all_authz(Authz.from_role(None)):
        updated_at = collection.updated_at.date().isoformat()
        updated_at = max(SETTINGS.SITEMAP_FLOOR, updated_at)
        url = collection_url(collection.id)
        collections.append({"url": url, "updated_at": updated_at})
    return render_xml("sitemap.xml", collections=collections)


@blueprint.route("/api/2/healthz")
def healthz():
    """
    ---
    get:
      summary: Health check endpoint.
      description: >
        Use health checks, this checks connections to Database, Archive, Redis,
        Elasticsearch and the oauth service (if configured).
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    example: 'ok'
      tags:
      - System
    """
    if SETTINGS.HEALTH_CHECK_API_KEY:
        api_key = request.args.get("api_key")
        if api_key != SETTINGS.HEALTH_CHECK_API_KEY:
            raise Unauthorized("Invalid or missing API key")

    _check_postgres()
    _check_elasticsearch()
    _check_redis()
    _check_archive()
    if SETTINGS.OAUTH:
        _check_oauth()

    return jsonify({"status": "ok"})


def _check_postgres():
    from openaleph_procrastinate.settings import OpenAlephSettings
    from sqlalchemy import create_engine, text

    settings = OpenAlephSettings()
    try:
        for db_uri in set(
            [settings.db_uri, settings.fragments_uri, settings.procrastinate_db_uri]
        ):
            # Use psycopg3 driver, matching core.py
            db_uri = db_uri.replace("postgresql://", "postgresql+psycopg://", 1)
            engine = create_engine(db_uri)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
    except Exception as exc:
        raise RuntimeError(f"PostgreSQL health check failed: {exc}")


def _check_elasticsearch():
    from openaleph_search.core import get_es

    try:
        es = get_es()
        es.info()
    except Exception as exc:
        raise RuntimeError(f"Elasticsearch health check failed: {exc}")


def _check_redis():
    try:
        redis = get_cache()
        redis.kv.ping()
    except Exception as exc:
        raise RuntimeError(f"Redis health check failed: {exc}")


def _check_archive():
    from openaleph_procrastinate.archive import get_archive

    try:
        archive = get_archive()
        archive.put("healthz", datetime.now())
    except Exception as exc:
        raise RuntimeError(f"Archive health check failed: {exc}")


def _check_oauth():
    try:
        from aleph.oauth import oauth

        oauth.provider.load_server_metadata()
    except Exception as exc:
        raise RuntimeError(f"OAuth health check failed: {exc}")


@blueprint.app_errorhandler(NotModified)
def handle_not_modified(err):
    return ("", 304)


@blueprint.app_errorhandler(400)
def handle_bad_request(err):
    if err.response is not None and err.response.is_json:
        return err.response
    return jsonify({"status": "error", "message": err.description}, status=400)


@blueprint.app_errorhandler(403)
def handle_authz_error(err):
    return jsonify(
        {
            "status": "error",
            "message": gettext("You are not authorized to do this."),
            "roles": request.authz.roles,
        },
        status=403,
    )


@blueprint.app_errorhandler(404)
def handle_not_found_error(err):
    msg = gettext("This path does not exist.")
    return jsonify({"status": "error", "message": msg}, status=404)


@blueprint.app_errorhandler(500)
def handle_server_error(err):
    log.exception("%s: %s", type(err).__name__, err)
    msg = gettext("Internal server error.")
    return jsonify({"status": "error", "message": msg}, status=500)


@blueprint.app_errorhandler(InvalidData)
def handle_invalid_data(err):
    data = {"status": "error", "message": str(err), "errors": err.errors}
    return jsonify(data, status=400)


@blueprint.app_errorhandler(DecodeError)
@blueprint.app_errorhandler(ExpiredSignatureError)
def handle_jwt_expired(err):
    log.info("JWT Error: %s", err)
    data = {"status": "error", "errors": gettext("Access token is invalid.")}
    return jsonify(data, status=401)


@blueprint.app_errorhandler(TransportError)
def handle_es_error(err):
    if hasattr(err, "errors"):  # FIXME why
        message = err.errors
    else:
        message = err.error
    if hasattr(err, "info") and isinstance(err.info, dict):
        error = err.info.get("error", {})
        for root_cause in error.get("root_cause", []):
            message = root_cause.get("reason", message)
    try:
        # Sometimes elasticsearch-py generates non-numeric status codes like
        # "TIMEOUT", "N/A". Werkzeug converts them into status 0 which confuses
        # web browsers. Replace the weird status codes with 500 instead.
        status = int(err.status_code)
    except (ValueError, AttributeError):
        status = 500
    return jsonify({"status": "error", "message": message}, status=status)
