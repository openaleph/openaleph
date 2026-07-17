"""Unit tests for the typed object resolver in
``aleph.logic.resolver.core``.

These are pure pydantic + anystore tests — no Aleph DB, no Flask app,
no Redis. The resolver's persistent store is pinned to ``memory://``
via ``ALEPH_RESOLVER_STORE_URI`` in ``[tool.pytest_env]``, and each
test starts from an empty store + empty registry via the autouse
fixture below.
"""

from collections.abc import Iterable
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from aleph.logic.resolver import (
    RequestResolver,
    compute_etag,
    register,
    register_etag,
)
from aleph.logic.resolver import registry as _registry


def _clear_registry() -> None:
    """Drop every fetch + ETag registration. Used by the autouse
    fixture below so each test starts from a clean registry. Lives
    here rather than in the registry module itself so production code
    has no test-only entry points."""
    _registry._REGISTRY.clear()
    _registry._ETAG_FNS.clear()


# --- toy models -----------------------------------------------------------


class Widget(BaseModel):
    """Tiny stand-in for a real schema. ``id`` is the resolver key,
    ``name`` is the only payload. Mirrors the ``cache_key`` contract
    of ``aleph.model.common.APIBaseModel`` so the resolver's
    ``get_many`` path can match fetched objects back to the lookup
    identifier."""

    id: str
    name: str

    @property
    def cache_key(self) -> str:
        return self.id


class Gadget(BaseModel):
    """Second class so registry isolation tests have something to
    distinguish against."""

    id: str
    color: str

    @property
    def cache_key(self) -> str:
        return self.id


# --- fixtures -------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_resolver_state():
    """Each test starts from an empty registry and an empty store.

    ``ALEPH_RESOLVER_STORE_URI`` is pinned to ``memory://`` in
    ``[tool.pytest_env]``, so ``get_resolver_store()`` always returns
    an in-memory anystore Store. ``anystore.get_store()`` caches the
    Store on (uri, backend_config), so the same instance is returned
    across tests — we wipe it via ``iterate_keys`` between tests
    instead of trying to mint a fresh one.

    The registry is scoped: we save the real registrations before the
    test, clear to empty, and restore afterwards — so module-level
    ``@register`` decorators for real schemas (Role, Entity, …) aren't
    permanently lost when running alongside the e2e test suite.
    """
    RequestResolver().flushall()
    # Save the real registrations (populated by module-level @register
    # decorators), clear to empty so the test owns the full registry,
    # then restore after.
    saved_registry = dict(_registry._REGISTRY)
    saved_etags = dict(_registry._ETAG_FNS)
    _clear_registry()
    yield
    RequestResolver().flushall()
    _clear_registry()
    _registry._REGISTRY.update(saved_registry)
    _registry._ETAG_FNS.update(saved_etags)


@pytest.fixture
def fetch_calls() -> dict:
    """Counter dict shared between the registered fetcher and the test
    body, so tests can assert how many times upstream was hit."""
    return {"one": 0, "many": 0}


@pytest.fixture
def widgets(fetch_calls):
    """Register a Widget fetcher backed by an in-memory dict.

    Returns the dict so tests can mutate the upstream state and verify
    the resolver picks it up via ``invalidate``.
    """
    upstream = {
        "1": Widget(id="1", name="alpha"),
        "2": Widget(id="2", name="beta"),
        "3": Widget(id="3", name="gamma"),
    }

    @register(Widget)
    def _fetch_widget(identifier: str) -> Widget | None:
        fetch_calls["one"] += 1
        return upstream.get(identifier)

    return upstream


# --- single-object API ----------------------------------------------------


def test_get_rejects_empty_identifier(widgets):
    """The Resolver deliberately does not handle None / empty input —
    it raises ValueError so accidental Nones surface as a loud error
    instead of silently returning empty data. Callers with an
    Optional source filter at the call site."""
    r = RequestResolver()
    with pytest.raises(ValueError):
        r.get(Widget, None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        r.get(Widget, "")


def test_get_hits_upstream_then_caches(widgets, fetch_calls):
    assert fetch_calls["one"] == 0

    r = RequestResolver()
    obj = r.get(Widget, "1")
    assert obj is not None
    assert obj.name == "alpha"
    assert fetch_calls["one"] == 1

    # Second call: served from local cache, fetch_one not called again.
    obj2 = r.get(Widget, "1")
    assert obj2 is not None
    assert obj2.name == "alpha"
    assert fetch_calls["one"] == 1


def test_get_persists_to_store_then_skips_upstream(widgets, fetch_calls):
    assert fetch_calls["one"] == 0

    r = RequestResolver()
    r.get(Widget, "1")
    assert fetch_calls["one"] == 1

    # New resolver instance — local cache is empty, but the persistent
    # store should still have it. Upstream must NOT be hit.
    r2 = RequestResolver()
    obj = r2.get(Widget, "1")
    assert obj is not None
    assert obj.name == "alpha"
    assert fetch_calls["one"] == 1


def test_get_negative_hit_is_local_only(widgets, fetch_calls):
    assert fetch_calls["one"] == 0

    r = RequestResolver()
    assert r.get(Widget, "missing") is None
    assert fetch_calls["one"] == 1

    # Same resolver: negative result is cached locally — no refetch.
    assert r.get(Widget, "missing") is None
    assert fetch_calls["one"] == 1

    # New resolver: negative is NOT persisted to the store, so upstream
    # is hit again. This is intentional — see core.py docstring.
    r2 = RequestResolver()
    assert r2.get(Widget, "missing") is None
    assert fetch_calls["one"] == 2


def test_get_after_invalidate_refetches(widgets, fetch_calls):
    assert fetch_calls["one"] == 0

    r = RequestResolver()
    r.get(Widget, "1")
    assert fetch_calls["one"] == 1

    # Mutate upstream then invalidate the persistent store.
    widgets["1"] = Widget(id="1", name="alpha-prime")
    RequestResolver().invalidate(Widget, "1")

    # New resolver: local cache empty, store empty → upstream refetch.
    r2 = RequestResolver()
    assert r2.get(Widget, "1").name == "alpha-prime"
    assert fetch_calls["one"] == 2


def test_refresh_fetches_from_upstream_and_updates_store(widgets, fetch_calls):
    """cache.refresh() re-fetches from upstream and writes to the
    persistent store, so subsequent reads get the fresh value."""
    r = RequestResolver()
    assert r.get(Widget, "1").name == "alpha"
    assert fetch_calls["one"] == 1

    # Mutate upstream.
    widgets["1"] = Widget(id="1", name="alpha-refreshed")

    # refresh() calls fetch_one and writes to the store.
    r.refresh(Widget, "1")
    assert fetch_calls["one"] == 2

    # New resolver: local empty, store has fresh value.
    r2 = RequestResolver()
    assert r2.get(Widget, "1").name == "alpha-refreshed"
    # Served from store, no additional upstream call.
    assert fetch_calls["one"] == 2


def test_invalidate_rejects_empty_identifier(widgets):
    """invalidate() carries the same non-empty contract as get() —
    callers must filter Optional sources upstream."""
    with pytest.raises(ValueError):
        RequestResolver().invalidate(Widget, None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        RequestResolver().invalidate(Widget, "")


def test_invalidate_many(widgets, fetch_calls):
    assert fetch_calls["one"] == 0

    r = RequestResolver()
    r.get(Widget, "1")
    r.get(Widget, "2")
    assert fetch_calls["one"] == 2

    RequestResolver().invalidate_many(Widget, ["1", "2"])

    r2 = RequestResolver()
    r2.get(Widget, "1")
    r2.get(Widget, "2")
    assert fetch_calls["one"] == 4


# --- batch API ------------------------------------------------------------


def test_get_many_empty(widgets):
    r = RequestResolver()
    assert r.get_many(Widget, []) == []
    assert r.get_many(Widget, ["", None]) == []  # type: ignore[list-item]


def test_get_many_omits_missing(widgets, fetch_calls):
    r = RequestResolver()
    result = r.get_many(Widget, ["1", "missing", "2"])
    assert sorted([w.id for w in result]) == ["1", "2"]


def test_get_many_uses_cache_key_not_id(fetch_calls):
    """The lookup identifier is the model's ``cache_key``, which may
    differ from its ``id``. Real-world example: CollectionSchema is
    looked up by ``foreign_id`` (string) but its ``id`` is the SQLA
    integer primary key. The resolver must match fetched objects back
    to the lookup identifier via ``cache_key``, otherwise nothing in
    the result dict would line up with the input list AND the cache
    layers would key off the wrong value (so the second call would
    refetch upstream)."""

    class Resource(BaseModel):
        id: int  # SQLA-style integer PK
        foreign_id: str  # what the resolver actually keys on
        name: str

        @property
        def cache_key(self) -> str:
            return self.foreign_id

    upstream = {
        "alpha": Resource(id=1, foreign_id="alpha", name="A"),
        "beta": Resource(id=2, foreign_id="beta", name="B"),
    }

    @register(Resource)
    def _fetch_resource(identifier: str) -> Resource | None:
        fetch_calls["one"] += 1
        return upstream.get(identifier)

    assert fetch_calls["one"] == 0

    # First call: cold cache. Two upstream fetches
    r = RequestResolver()
    result = r.get_many(Resource, ["alpha", "beta"])
    assert sorted([x.foreign_id for x in result]) == ["alpha", "beta"]
    assert fetch_calls["one"] == 2

    # Same resolver, same ids: served from local cache, no upstream.
    result = r.get_many(Resource, ["alpha", "beta"])
    assert sorted([x.foreign_id for x in result]) == ["alpha", "beta"]
    assert fetch_calls["one"] == 2

    # Fresh resolver: local is empty, but the persistent store should
    # have both entries keyed by foreign_id. Still no upstream fetch.
    r2 = RequestResolver()
    result = r2.get_many(Resource, ["alpha", "beta"])
    assert sorted([x.foreign_id for x in result]) == ["alpha", "beta"]
    assert fetch_calls["one"] == 2


def test_get_many_uses_batch_fetcher_when_registered(fetch_calls):
    upstream = {
        "1": Widget(id="1", name="alpha"),
        "2": Widget(id="2", name="beta"),
    }

    def _fetch_many(ids: Iterable[str]):
        fetch_calls["many"] += 1
        for i in ids:
            obj = upstream.get(i)
            if obj is not None:
                yield obj

    @register(Widget, fetch_many=_fetch_many)
    def _fetch_one(identifier: str) -> Widget | None:
        fetch_calls["one"] += 1
        return upstream.get(identifier)

    assert fetch_calls["one"] == 0
    assert fetch_calls["many"] == 0

    r = RequestResolver()
    result = r.get_many(Widget, ["1", "2"])
    assert sorted([w.id for w in result]) == ["1", "2"]
    # Batched path: one call to fetch_many, zero to fetch_one.
    assert fetch_calls["many"] == 1
    assert fetch_calls["one"] == 0


def test_get_many_falls_back_to_fetch_one_without_batch(widgets, fetch_calls):
    assert fetch_calls["one"] == 0

    r = RequestResolver()
    result = r.get_many(Widget, ["1", "2", "3"])
    assert sorted([w.id for w in result]) == ["1", "2", "3"]
    # No fetch_many registered → 3 fetch_one calls.
    assert fetch_calls["one"] == 3


def test_get_many_layered_cache(widgets, fetch_calls):
    """Three ids: one in local, one in store, one upstream-only.
    Verifies the resolver doesn't double-fetch any layer."""
    assert fetch_calls["one"] == 0

    r = RequestResolver()
    r.get(Widget, "1")  # warms local + store for id=1
    assert fetch_calls["one"] == 1

    # Fresh resolver: id=1 will be served from store, id=2 from upstream.
    r2 = RequestResolver()
    r2.get(Widget, "2")  # warms store for id=2 (now in r2's local too)
    assert fetch_calls["one"] == 2

    # Now ask for all three. id=1 + id=2 are in r2's local cache; id=3
    # comes from upstream. fetch_one should be called exactly once.
    r2.get_many(Widget, ["1", "2", "3"])
    assert fetch_calls["one"] == 3


def test_get_many_negative_local_cache_blocks_refetch(widgets, fetch_calls):
    """The _MISSING sentinel: a None recorded in self._local must
    block subsequent fetches in the SAME request, otherwise repeated
    references to a deleted entity would each hit upstream."""
    assert fetch_calls["one"] == 0

    r = RequestResolver()
    r.get(Widget, "missing")
    assert fetch_calls["one"] == 1

    # get_many for the same id within the same request should NOT
    # refetch — the negative hit is in local cache.
    result = r.get_many(Widget, ["missing"])
    assert result == []
    assert fetch_calls["one"] == 1


# --- ETag API -------------------------------------------------------------


def test_get_etag_default_hash(widgets):
    r = RequestResolver()
    etag = r.get_etag(Widget, "1")
    assert etag is not None
    # Quoted (RFC 7232) and compact (~13 chars).
    assert etag.startswith('"') and etag.endswith('"')
    assert len(etag) == 13


def test_get_etag_stable_for_same_content(widgets):
    r = RequestResolver()
    e1 = r.get_etag(Widget, "1")
    e2 = r.get_etag(Widget, "1")
    assert e1 == e2


def test_get_etag_changes_when_content_changes(widgets):
    r = RequestResolver()
    e1 = r.get_etag(Widget, "1")

    widgets["1"] = Widget(id="1", name="alpha-prime")
    RequestResolver().invalidate(Widget, "1")

    r2 = RequestResolver()
    e2 = r2.get_etag(Widget, "1")
    assert e1 != e2


def test_get_etag_returns_none_for_missing(widgets):
    r = RequestResolver()
    assert r.get_etag(Widget, "missing") is None


def test_register_etag_overrides_default(widgets):
    """The registered function returns a raw seed string; the decorator
    wraps it with _short_hash + quoting so the on-wire ETag is always
    opaque and compact."""

    @register_etag(Widget)
    def _widget_etag(obj: Widget) -> str:
        return f"{obj.id}:{obj.name}"

    r = RequestResolver()
    etag = r.get_etag(Widget, "1")
    assert etag is not None
    # Opaque, quoted, compact — no raw id or name leaking.
    assert etag.startswith('"') and etag.endswith('"')
    assert len(etag) == 13
    assert "1" not in etag[1:-1] or len(etag[1:-1]) == 11  # hash, not literal

    # Different content → different hash.
    widgets["1"] = Widget(id="1", name="alpha-prime")
    RequestResolver().invalidate(Widget, "1")
    r2 = RequestResolver()
    assert r2.get_etag(Widget, "1") != etag


def test_compute_etag_direct():
    """compute_etag is also usable on a model that isn't registered
    in the resolver registry — it falls back to a content hash."""
    w = Widget(id="x", name="hello")
    etag = compute_etag(Widget, w)
    assert len(etag) == 13


def test_get_many_etag_combines_constituents(widgets):
    r = RequestResolver()
    combined = r.get_many_etag(Widget, ["1", "2", "3"])
    assert combined.startswith('"') and combined.endswith('"')

    # Same input → same etag.
    r2 = RequestResolver()
    assert r2.get_many_etag(Widget, ["1", "2", "3"]) == combined


def test_get_many_etag_changes_with_content(widgets):
    r = RequestResolver()
    before = r.get_many_etag(Widget, ["1", "2"])

    widgets["1"] = Widget(id="1", name="alpha-prime")
    RequestResolver().invalidate(Widget, "1")

    r2 = RequestResolver()
    after = r2.get_many_etag(Widget, ["1", "2"])
    assert before != after


def test_get_many_etag_with_extra_discriminator(widgets):
    r = RequestResolver()
    plain = r.get_many_etag(Widget, ["1", "2"])
    filtered = r.get_many_etag(Widget, ["1", "2"], extra="?q=foo")
    assert plain != filtered


# --- registry behaviour ---------------------------------------------------


def test_unregistered_class_raises_keyerror(widgets):
    """Asking for a class that has no registered fetcher should raise
    KeyError — silent None would mask programming bugs."""
    r = RequestResolver()
    with pytest.raises(KeyError):
        r.get(Gadget, "1")


def test_per_class_ttl_is_passed_to_store(widgets):
    """register(..., ttl=60) should reach Store.put as ttl=60. We
    spy on the underlying store to verify."""

    @register(Gadget, ttl=60)
    def _fetch_gadget(identifier: str) -> Gadget | None:
        return Gadget(id=identifier, color="red")

    r = RequestResolver()
    r._store = MagicMock(wraps=r._store)
    r._store.get = MagicMock(return_value=None)
    r.get(Gadget, "abc")

    # Inspect the put() call.
    assert r._store.put.called
    call_kwargs = r._store.put.call_args.kwargs
    assert call_kwargs["ttl"] == 60
    assert call_kwargs["model"] is Gadget


def test_default_ttl_is_none(widgets):
    """Without an explicit ttl on register(), Store.put gets ttl=None
    (which means: use the store's default)."""
    r = RequestResolver()
    r._store = MagicMock(wraps=r._store)
    r._store.get = MagicMock(return_value=None)
    r.get(Widget, "1")

    assert r._store.put.called
    assert r._store.put.call_args.kwargs["ttl"] is None


# --- key construction -----------------------------------------------------


def test_key_format_is_path_style():
    assert RequestResolver._key(Widget, "1") == "Widget/1"
    assert RequestResolver._key(Widget, "foo/stats") == "Widget/foo/stats"
