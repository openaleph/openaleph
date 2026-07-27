"""Consolidated auth state store (phase-0d cache teardown).

One Redis-backed anystore Store rooted at ``{REDIS_URL}/authz`` carries
every piece of auth state. It is **Redis-only by design** (no URI
override): the role ACL snapshot lives in a single raw Redis hash so
that ``flush_acl()`` can invalidate every role's ACL atomically with one
``DEL`` – a permission change on a public collection affects an
unknowable set of roles, and a plain key-value store could only offer a
racy scan-and-delete for that. Everything else uses the regular Store
API under path-namespaced keys:

- ``tokens/<role_id>/<random>`` – session-token state; a role's tokens
  are exactly one path prefix, so blocked-role revocation is a prefix
  iteration (see ``revoke_tokens``).
- ``oauth-sess/<state>`` – transient OAuth handshake state.
- ``oauth-id-tok/<token>`` – OIDC id-tokens (for the logout redirect).
- ``authlib/<key>`` – authlib's internal cache (server metadata etc.),
  written through the generic put/get/delete by ``aleph.oauth``.
"""

import json
from typing import ClassVar

from anystore.store import Store
from anystore.types import SDict
from redis import Redis

from aleph.settings import REDIS_URL, SETTINGS


class AuthzStore(Store):
    """Auth state: role ACL snapshots, session tokens, OAuth state."""

    # The ACL hash sits next to (not inside) the Store keyspace: hash
    # fields are role ids, values the JSON {"read": [...], "write": [...]}
    # snapshots computed by Authz.collections().
    ACL_HASH: ClassVar[str] = "authz/acl"

    @property
    def _kv(self) -> Redis:
        # the store's own backend connection (same Redis as get_redis())
        return self._fs._con

    # -- role ACL snapshots (raw Redis hash) ---

    def get_acl(self, role_id: str | int) -> SDict | None:
        value = self._kv.hget(self.ACL_HASH, str(role_id))
        if value is None:
            return None
        return json.loads(value)

    def set_acl(self, role_id: str | int, acl: SDict) -> None:
        self._kv.hset(self.ACL_HASH, str(role_id), json.dumps(acl))

    def delete_acl(self, role_id: str | int) -> None:
        self._kv.hdel(self.ACL_HASH, str(role_id))

    def flush_acl(self) -> None:
        """Atomically invalidate every role's ACL snapshot."""
        self._kv.delete(self.ACL_HASH)

    # -- session tokens ---

    def put_token(self, token_id: str, state: SDict, ttl: int | None = None) -> None:
        self.put(f"tokens/{token_id}", state, ttl=ttl)

    def get_token(self, token_id: str) -> SDict | None:
        return self.get(f"tokens/{token_id}")

    def delete_token(self, token_id: str) -> None:
        self.delete(f"tokens/{token_id}", ignore_errors=True)

    def revoke_tokens(self, role_id: str | int) -> None:
        """End all of a role's sessions (token ids are "<role_id>/…")."""
        for key in self.iterate_keys(prefix=f"tokens/{role_id}"):
            self.delete(key, ignore_errors=True)

    # -- OAuth handshake state / OIDC id-tokens ---

    def put_oauth_state(self, state_id: str, state: SDict, ttl: int = 3600) -> None:
        self.put(f"oauth-sess/{state_id}", state, ttl=ttl)

    def get_oauth_state(self, state_id: str) -> SDict | None:
        return self.get(f"oauth-sess/{state_id}")

    def put_id_token(self, token_id: str, id_token: str) -> None:
        self.put(f"oauth-id-tok/{token_id}", id_token)

    def get_id_token(self, token_id: str) -> str | None:
        return self.get(f"oauth-id-tok/{token_id}")


authz_store = AuthzStore(
    uri=f"{REDIS_URL}/authz",
    raise_on_nonexist=False,
    default_ttl=SETTINGS.SESSION_EXPIRE,
)
