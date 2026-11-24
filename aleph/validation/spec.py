DESCRIPTION = """
OpenAleph - The open source platform that securely stores large amounts of 
data and makes it searchable for easy collaboration.

# General Overview

The OpenAleph web interface is powered by a Flask HTTP API. OpenAleph supports an
extensive API for searching documents and entities. It can also be used to
retrieve raw metadata, source documents and other useful details. OpenAleph's
API tries to follow a pragmatic approach based on the following principles:

- All API calls are prefixed with an API version; this version is `/api/2/`.

- Responses and requests are both encoded as JSON. Requests should have the
`Content-Type` and `Accept` headers set to `application/json`.

- The application uses Representational State Transfer (REST) principles
where convenient, but also has some procedural API calls.

- The API allows API Authorization via an API key or JSON Web Tokens.

# Authentication and Authorization

By default, any search will return only public documents in responses
to API requests.

If you want to access documents which are not marked public, you will need
to sign into the tool. This can be done through the use on an **API key**.
The API key for any account can be found by clicking on the "Profile" menu
item in the navigation menu.

The API key must be sent on all queries using the `Authorization` HTTP
header:

```Authorization: ApiKey 363af1e2b03b41c6b3adc604956e2f66```

Alternatively, the API key can also be sent as a query parameter under the
`api_key` key.

Similarly, a JWT can be sent in the Authorization header, after it has been
returned by the login and/or OAuth processes. OpenAleph does not use session
cookies or any other type of stateful API.

## Scoped API tokens

An API key grants everything its user can do and does not expire. Scripts and
integrations that need less should use a **scoped API token**: a credential
limited to a list of collections and to a lifetime, created with
`POST /api/2/tokens` (which requires the API key or a session). It is sent
like an API key, but only in the header:

```Authorization: ApiKey scoped.42.1f0c9d3a5b7e2468.kq3...```

A scoped token can read and write data in the collections it lists, as far as
its user can at the time of the request. It is never an administrator, cannot
manage the account, permissions, collections or other tokens, and is refused
as an `api_key` query parameter. Whether an instance supports scoped tokens
is announced as `auth.scoped_tokens_uri` in `/api/2/metadata`.
"""

spec_info = {
    "description": DESCRIPTION,
    "contact": {"url": "https://github.com/openaleph/openaleph"},
    "license": {
        "name": "MIT",
        "url": "https://github.com/openaleph/openaleph/blob/main/LICENSE.txt",
    },
    "x-logo": {
        "altText": "OpenAleph logo",
        "url": "https://avatars.githubusercontent.com/u/203699126?s=200&v=4",
    },
}

spec_docs = {
    "description": "Find out more about OpenAleph, the information search tool for investigators.",
    "url": "https://openaleph.org/",
}

spec_tags = [
    {
        "description": "Search, create and manage entities.",
        "name": "Entity",
        "x-displayName": "Entities and Search API",
    },
    {
        "description": "Create and manage collections.",
        "name": "Collection",
        "x-displayName": "Collections API",
    },
    {
        "description": "Create and manage mappings.",
        "name": "Mapping",
        "x-displayName": "Mappings API",
    },
    {
        "description": "Create and manage network diagrams.",
        "name": "Diagram",
        "x-displayName": "Network Diagrams API",
    },
    {
        "description": "Create and manage alerts.",
        "name": "Alert",
        "x-displayName": "Alerts API",
    },
    {
        "description": "Download blobs from the archive.",
        "name": "Archive",
        "x-displayName": "Archive API",
    },
    {
        "description": "Cross-reference entities of a collection with other collections.",  # noqa
        "name": "Xref",
        "x-displayName": "Cross-reference API",
    },
    {
        "description": "Manage users, groups and sessions",
        "name": "Role",
        "x-displayName": "Roles & Groups API",
    },
    {
        "description": "Upload documents to a collection.",
        "name": "Ingest",
        "x-displayName": "Ingest API",
    },
    {
        "description": "Fetch and manage notifications",
        "name": "Notification",
        "x-displayName": "Notifications API",
    },
    {
        "description": "Fetch and manage permissions on a collection",
        "name": "Permission",
        "x-displayName": "Permissions API",
    },
    {
        "description": "Fetch and delete query logs",
        "name": "Query Log",
        "x-displayName": "Query Log API",
    },
    {
        "description": "System-wide APIs",
        "name": "System",
        "x-displayName": "System-wide API",
    },
    {
        "description": "Create and manage bookmarks",
        "name": "Bookmarks",
        "x-displayName": "Bookmarks API",
    },
]
