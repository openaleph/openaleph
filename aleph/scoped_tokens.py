"""Scoped, expiring API tokens.

A scoped token is a credential a user creates for one purpose (a script, an
integration, an unattended job). It is limited to a named list of collections
and to a lifetime, so that leaking it exposes far less than leaking the user's
API key, which grants everything the user can do and never expires.

This module only knows about the token *state record* and how to store,
verify and revoke it. What a scoped token is allowed to do is decided in
``aleph.authz.Authz`` (see ``Authz.from_scoped_token``) and in
``aleph.views.context`` (the endpoint allowlist).

The record is kept in Redis next to the session tokens, one key per token
with a TTL, under a per-role prefix so that all tokens of a role can be
revoked together. Only a SHA-256 digest of the secret is stored: the
credential cannot be recovered from the store.

Every reader in here fails closed: a record that is missing, expired,
malformed, of an unknown version or bound to another role yields
``Unauthorized`` -- never the owner's regular access.
"""

import hashlib
import hmac
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Any, NamedTuple

from werkzeug.exceptions import Unauthorized

from aleph.core import cache
from aleph.model import Collection
from aleph.model.common import make_token
from aleph.settings import SETTINGS

log = logging.getLogger(__name__)

# Credential format: ``scoped.<role_id>.<key_id>.<secret>``. API keys and
# session secrets are made by ``make_token`` (URL-safe base64, never contains
# a dot), so this prefix cannot collide with an existing credential.
PREFIX = "scoped"
VERSION = 1
# Cache namespace of the state records (``Authz.TOKENS`` is "authztk").
STORE = "authzst"

MAX_TOKENS_PER_ROLE = 25
MAX_COLLECTIONS = 100
MAX_LABEL = 100

READ = "read"
WRITE = "write"

ROLE_ID_RE = re.compile(r"^[1-9][0-9]{0,17}$")
KEY_ID_RE = re.compile(r"^[0-9a-f]{16}$")
SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
RECORD_FIELDS = frozenset(
    (
        "v",
        "role_id",
        "key_id",
        "secret_hash",
        "label",
        "read",
        "write",
        "created_at",
        "expires_at",
    )
)


class Scope(NamedTuple):
    """The verified limits of a scoped token, as attached to an ``Authz``."""

    role_id: int
    key_id: str
    read: frozenset[int]
    write: frozenset[int]

    def collections(self, action: str) -> frozenset[int]:
        if action == READ:
            return self.read
        if action == WRITE:
            return self.write
        return frozenset()


def is_scoped_token(credential: Any) -> bool:
    """Whether a credential is meant to be a scoped token. Deliberately
    loose (case, surrounding whitespace): whatever looks like one is then
    verified strictly by `load_scope` and never tried as an API key."""
    if not isinstance(credential, str):
        return False
    return credential.strip().lower().startswith(PREFIX + ".")


def is_enabled() -> bool:
    return SETTINGS.SCOPED_TOKEN_MAX_EXPIRE > 0


def _key(role_id: int | str, key_id: str) -> str:
    return cache.key(STORE, "%s.%s" % (role_id, key_id))


def _role_prefix(role_id: int | str) -> str:
    # The trailing dot keeps role 1 from matching the keys of role 12.
    return cache.key(STORE, "%s." % role_id)


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _is_id_list(value: Any) -> bool:
    if not isinstance(value, list) or len(value) > MAX_COLLECTIONS:
        return False
    # bool is a subclass of int, hence the exact type check.
    return all(type(v) is int and v > 0 for v in value)


def _valid_record(record: Any, now: float) -> bool:
    """Check a stored record in full. Anything unexpected makes it invalid."""
    if not isinstance(record, dict) or set(record.keys()) != RECORD_FIELDS:
        return False
    if type(record["v"]) is not int or record["v"] != VERSION:
        return False
    if type(record["role_id"]) is not int or record["role_id"] < 1:
        return False
    for field, regex in (("key_id", KEY_ID_RE), ("secret_hash", DIGEST_RE)):
        if not isinstance(record[field], str) or not regex.fullmatch(record[field]):
            return False
    if not isinstance(record["label"], str) or len(record["label"]) > MAX_LABEL:
        return False
    if not _is_id_list(record["read"]) or not _is_id_list(record["write"]):
        return False
    if not len(record["read"]) or not set(record["write"]) <= set(record["read"]):
        return False
    created_at, expires_at = record["created_at"], record["expires_at"]
    if type(created_at) is not int or type(expires_at) is not int:
        return False
    # The store's TTL already removes expired records. Checking here as well
    # means a clock or TTL mishap cannot extend a token, and that lowering
    # the configured maximum ends the tokens that exceed it.
    if expires_at <= now or expires_at <= created_at:
        return False
    if expires_at - created_at > SETTINGS.SCOPED_TOKEN_MAX_EXPIRE:
        return False
    return True


def _read_record(role_id: int | str, key_id: str, now: float) -> dict | None:
    """Load and validate one record; `None` for every kind of failure."""
    try:
        record = cache.get_complex(_key(role_id, key_id))
    except Exception:
        log.exception("Cannot read scoped token: %s.%s", role_id, key_id)
        return None
    if not _valid_record(record, now):
        return None
    # The record must sit under the key it claims to belong to.
    if str(record["role_id"]) != str(role_id) or record["key_id"] != key_id:
        return None
    return record


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _public(record: dict) -> dict:
    """The part of a record that may be shown to its owner."""
    return {
        "id": record["key_id"],
        "label": record["label"],
        "read": sorted(record["read"]),
        "write": sorted(record["write"]),
        "created_at": _iso(record["created_at"]),
        "expires_at": _iso(record["expires_at"]),
    }


def list_scoped_tokens(role_id: int) -> list[dict]:
    """All valid tokens of a role, oldest first. Never includes secrets."""
    now = time.time()
    prefix = _role_prefix(role_id)
    records = []
    for key in cache.kv.scan_iter(match="%s*" % prefix):
        if isinstance(key, bytes):
            key = key.decode("utf-8")
        record = _read_record(role_id, key[len(prefix) :], now)
        if record is not None:
            records.append(record)
    records.sort(key=lambda r: (r["created_at"], r["key_id"]))
    return [_public(r) for r in records]


def create_scoped_token(
    role_id: int, label: str, read: list[int], write: list[int], expires_in: int
) -> dict:
    """Store a new token for the role and return its public record plus the
    credential under ``token``. This is the only time the credential exists
    in clear; the caller must have validated the arguments."""
    now = int(time.time())
    key_id = secrets.token_hex(8)
    secret = make_token()
    record = {
        "v": VERSION,
        "role_id": int(role_id),
        "key_id": key_id,
        "secret_hash": _digest(secret),
        "label": label,
        "read": sorted(set(read)),
        "write": sorted(set(write)),
        "created_at": now,
        "expires_at": now + int(expires_in),
    }
    if not _valid_record(record, now):
        raise ValueError("Invalid scoped token")
    cache.set_complex(_key(role_id, key_id), record, expires=int(expires_in))
    log.info("Scoped token created: %s.%s", role_id, key_id)
    data = _public(record)
    data["token"] = ".".join((PREFIX, str(int(role_id)), key_id, secret))
    return data


def revoke_scoped_token(role_id: int, key_id: str) -> bool:
    """Revoke one token of the given role. `False` if there is none."""
    if not isinstance(key_id, str) or not KEY_ID_RE.fullmatch(key_id):
        return False
    deleted = cache.kv.delete(_key(role_id, key_id))
    if deleted:
        log.info("Scoped token revoked: %s.%s", role_id, key_id)
    return bool(deleted)


def revoke_scoped_tokens(role_id: int) -> None:
    """Revoke all tokens of a role."""
    cache.flush(prefix=_role_prefix(role_id))


def burn_scoped_token(credential: str) -> None:
    """Revoke a token that was presented where it must not be (in a URL),
    since it may now sit in logs. Only a genuine token is revoked, so this
    cannot be used to revoke somebody else's."""
    try:
        scope = load_scope(credential)
    except Unauthorized:
        return
    revoke_scoped_token(scope.role_id, scope.key_id)


def load_scope(credential: str) -> Scope:
    """Verify a presented credential and return its limits.

    Raises ``Unauthorized`` for anything but a well-formed credential whose
    secret matches a valid, unexpired record and whose collections all still
    exist. The credential is never logged and never part of the error.
    """
    if not is_enabled() or not isinstance(credential, str):
        raise Unauthorized()
    parts = credential.split(".")
    if len(parts) != 4 or parts[0] != PREFIX:
        raise Unauthorized()
    _, role_id, key_id, secret = parts
    if not (
        ROLE_ID_RE.fullmatch(role_id)
        and KEY_ID_RE.fullmatch(key_id)
        and SECRET_RE.fullmatch(secret)
    ):
        raise Unauthorized()

    record = _read_record(role_id, key_id, time.time())
    # Compare in constant time, and also when there is no record, so that
    # the response time does not depend on how much of the secret is right.
    expected = record["secret_hash"] if record is not None else "0" * 64
    matches = hmac.compare_digest(expected, _digest(secret))
    if record is None or not matches:
        raise Unauthorized()

    # A token naming a collection that is gone is treated as broken rather
    # than silently narrowed: its owner should issue a new one.
    q = Collection.all_ids().filter(Collection.id.in_(record["read"]))
    existing = set(id_ for (id_,) in q)
    if existing != set(record["read"]):
        raise Unauthorized()

    return Scope(
        role_id=record["role_id"],
        key_id=record["key_id"],
        read=frozenset(record["read"]),
        write=frozenset(record["write"]),
    )
