"""Future-FastAPI API layer.

This package will host the FastAPI app as the Flask → FastAPI migration
progresses. Today it contains the request body schemas
(``aleph.api.requests``, consumed by the Flask views via
``validate_request``/``request_data``), the response assemblers
(``aleph.api.assemblers``) and the not-yet-wired FastAPI scaffolding
(``routers``/``dependencies``, reserved for the next stage).

The dependency direction is strictly ``aleph.api → aleph.model`` –
nothing in ``aleph.model`` imports from here.
"""
