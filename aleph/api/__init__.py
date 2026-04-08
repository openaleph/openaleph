"""Future-FastAPI API layer.

This package will host the FastAPI app, dependencies, routers and request
schemas as the Flask → FastAPI migration progresses. Today it only
contains the request body schemas (``aleph.api.requests``) which Flask
views import for ``parse_pydantic`` validation.

The dependency direction is strictly ``aleph.api → aleph.model`` —
nothing in ``aleph.model`` imports from here.
"""
