# Docker Build System

This document explains how Aleph's Docker images are built, both locally and in CI.

## Overview

Aleph uses multi-stage Docker builds to optimize image size and build times:

```mermaid
flowchart LR
    subgraph Backend
        B1[builder] --> B2[models]
        B2 --> B3[runtime]
    end

    subgraph UI
        U1[deps] --> U2[builder]
        U2 --> U3[production]
    end
```

## Backend Dockerfile

The backend image (`Dockerfile`) uses three stages:

### Stage 1: Builder

Installs build dependencies and compiles Python packages:

- Installs `build-essential`, `libicu-dev`, `libpq-dev`
- Creates a virtual environment at `/opt/venv`
- Compiles `pyicu` from source (requires ICU libraries)
- Installs all Python dependencies with `--no-deps` (frozen requirements)
- Installs the `aleph` package itself
- Cleans up `__pycache__`, test files, and docs to reduce size

### Stage 2: Models

Downloads machine learning models for entity matching:

- Word frequency model for text comparison
- GLM Bernoulli model for cross-referencing

### Stage 3: Runtime

Minimal production image:

- Based on `python:3.13-slim`
- Only runtime dependencies (`libicu76`, `libpq5`, `postgresql-client`)
- Copies virtual environment from builder
- Copies models from models stage
- Runs as non-root user (`app:app`)
- Default entrypoint runs Gunicorn

**Key environment variables** (set in Dockerfile):

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENALEPH_ELASTICSEARCH_URI` | `http://elasticsearch:9200/` | Elasticsearch connection |
| `OPENALEPH_DB_URI` | `postgresql://aleph:aleph@postgres/aleph` | Main database |
| `FTM_FRAGMENTS_URI` | `postgresql://aleph:aleph@postgres/aleph` | FTM fragments storage |
| `REDIS_URL` | `redis://redis:6379/0` | Redis cache |
| `PROCRASTINATE_APP` | `aleph.procrastinate.tasks.app` | Task queue app |
| `OPENALEPH_SEARCH_AUTH` | `1` | Enable search authorization |
| `OPENALEPH_SEARCH_AUTH_FIELD` | `collection_id` | Authorization field |

## UI Dockerfile

The UI image (`ui/Dockerfile`) uses three stages:

### Stage 1: Deps

Installs npm dependencies:

- Uses `npm ci --ignore-scripts` for reproducible installs
- Caches `node_modules` for subsequent builds

### Stage 2: Builder

Builds the production bundle:

- Runs `npm rebuild` for native dependencies
- Generates translation messages
- Creates optimized production build

### Stage 3: Production

Minimal nginx image:

- Based on `nginx:alpine`
- Only contains the built static files
- Configured for single-page application routing

## Building Locally

```bash
# Build backend image
make build

# Build UI image
make build-ui

# Build both
make build-all

# Build with custom tag
ALEPH_TAG=dev make build
```

## GitHub Actions CI

The CI workflow (`.github/workflows/build.yml`) runs on every push to the repository.

### Workflow Overview

```mermaid
flowchart TD
    A[Push to repo] --> B[Start services]
    B --> C[Build Docker image]
    C --> D[Run tests in container]
    D --> E{Tests pass?}
    E -->|Yes| F[Check formatting]
    E -->|No| G[Fail]
    F --> H{Format OK?}
    H -->|Yes| I[Build & push release]
    H -->|No| G
```

### GitHub Actions Services

The workflow uses GitHub Actions services instead of docker-compose:

```yaml
services:
  postgres:
    image: postgres:17
    ports:
      - 5432:5432

  elasticsearch:
    image: ghcr.io/openaleph/elasticsearch:9
    ports:
      - 9200:9200

  redis:
    image: redis:alpine
    ports:
      - 6379:6379
```

### Test Execution

Tests run inside the built Docker image with `--network host` to access the services:

```bash
docker run --rm \
  --network host \
  -e OPENALEPH_ELASTICSEARCH_URI=http://localhost:9200 \
  -e OPENALEPH_DB_URI=postgresql://aleph:aleph@localhost:5432/aleph \
  ... \
  ghcr.io/openaleph/openaleph:$SHA \
  sh -c "pip install -r requirements-dev.txt && pytest"
```

Only connection URIs are overridden since other environment variables are already set in the Dockerfile.

### Image Tags

Released images are tagged based on the git reference:

| Git Reference | Image Tag |
|--------------|-----------|
| Branch push | `branch-name` |
| Tag (semver) | `v1.2.3` |
| Any commit | `sha-abc1234` |
| Release tag | `latest` |

### Docker Build Caching

The workflow uses GitHub Actions cache for Docker layers:

```yaml
cache-from: type=gha
cache-to: type=gha,mode=max
```

This significantly speeds up builds by reusing unchanged layers.

## UI CI Workflow

The UI workflow (`.github/workflows/build-ui.yml`) follows a similar pattern:

1. Build the Docker image
2. Push to GitHub Container Registry
3. Tag based on git reference

## Container Registry

All images are published to GitHub Container Registry:

- Backend: `ghcr.io/openaleph/openaleph`
- UI: `ghcr.io/openaleph/aleph-ui`

## Local Development vs Production

| Aspect | Local Development | Production |
|--------|------------------|------------|
| Services | Docker Compose | Managed services or Docker |
| Backend | Local Python | Docker container |
| UI | Local npm dev server | Nginx in Docker |
| Hot reload | Yes | No |
| Debug mode | Enabled | Disabled |

For local development setup, see the [Setup Guide](setup.md).
