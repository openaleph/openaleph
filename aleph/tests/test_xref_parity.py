"""
API-parity guard: XrefResolver stays signature-compatible with
nomenklatura's Resolver.

XrefResolver deliberately does not subclass nomenklatura's Resolver (since
4.11 upstream inlines SQL into every method — no storage seam, and its
in-memory linker is auth-blind). This test is the binding to the shared
concept instead: for every shared method, our signature must accept
upstream's calling convention — same leading parameter names, extras
optional. It fails loudly when upstream moves the concept. No database or
ES needed.
"""

import inspect

from nomenklatura.resolver.resolver import Resolver

from aleph.logic.xref.resolver import XrefResolver

SHARED_METHODS = (
    "decide",
    "suggest",
    "get_judgement",
    "get_canonical",
    "get_referents",
    "connected",
    "canonicals",
    "get_edge",
    "get_resolved_edge",
    "check_candidate",
    "get_candidates",
    "get_judgements",
    "get_linker",
    "apply_statement",
    "remove",
    "explode",
)

# Methods that exist on both but whose signatures deliberately diverge.
# (commit/close/bulk/import_decisions are aleph-only extensions: upstream
# 4.11 dropped commit/close with its session rewrite.)
DELIBERATE_DIVERGENCES = {
    "prune": "cleanup_after dropped — aleph prune only clears ES suggestions",
    "dump": "takes an anystore Uri instead of a PathLike path",
    "load": "takes an anystore Uri instead of a PathLike path",
}

VARIADIC = (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)


def test_shared_methods_signature_compatible():
    for name in SHARED_METHODS:
        upstream = inspect.signature(getattr(Resolver, name))
        ours = inspect.signature(getattr(XrefResolver, name))
        up_params = [p for p in upstream.parameters.values() if p.kind not in VARIADIC]
        our_params = list(ours.parameters.values())

        # Upstream's positional/keyword calling convention must work on ours:
        # same leading parameter names, in order.
        for i, up in enumerate(up_params):
            assert i < len(our_params), f"{name}: missing parameter {up.name!r}"
            assert our_params[i].name == up.name, (
                f"{name}: parameter {i} is {our_params[i].name!r}, "
                f"upstream has {up.name!r}"
            )

        # Anything we add on top must be optional so upstream-style calls
        # keep working unchanged.
        for extra in our_params[len(up_params) :]:
            assert (
                extra.default is not inspect.Parameter.empty or extra.kind in VARIADIC
            ), f"{name}: extra parameter {extra.name!r} must be optional"


def test_divergent_methods_exist():
    """Deliberate divergences still have to exist as methods at all."""
    for name in DELIBERATE_DIVERGENCES:
        assert callable(getattr(XrefResolver, name)), name
        assert callable(getattr(Resolver, name)), f"{name} gone upstream"
