# Development Setup

This guide walks you through setting up a complete local development environment for Aleph.

## 1. Clone the Repository

```bash
git clone https://github.com/openaleph/openaleph.git
cd openaleph
```

## 2. Environment Configuration

The Makefile exports sensible defaults for local development:

| Variable | Default Value |
|----------|---------------|
| `ALEPH_DEBUG` | `true` |
| `ALEPH_SECRET_KEY` | `development` |
| `ALEPH_SINGLE_USER` | `true` |
| `OPENALEPH_ELASTICSEARCH_URI` | `http://localhost:9200` |
| `OPENALEPH_DB_URI` | `postgresql://aleph:aleph@localhost:5432/aleph` |
| `REDIS_URL` | `redis://localhost:6379` |

!!! warning "Single User Mode"
    `ALEPH_SINGLE_USER=true` disables authentication for easier local development.
    Never use this in production.

## 3. Start Services

Start the required services using Docker Compose:

```bash
make services
```

This starts (from the `docker-compose.yml`):

- **PostgreSQL** (port 5432) - Main database
- **Elasticsearch** (port 9200) - Search engine
- **Redis** (port 6379) - Task queue and caching
- **ingest-file** - Document processing worker
- **ftm-analyze** - Entity analysis worker

You can check the status with:

```bash
docker compose ps
```

## 4. Backend Setup

### Install Python Dependencies

For development, install both runtime and dev dependencies:

```bash
make dev
```

This installs:

- `requirements.txt` - Runtime dependencies
- `requirements-dev.txt` - Development tools (pytest, black, ruff, etc.)

!!! tip "Virtual Environment"
    We recommend using a virtual environment:
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    make dev
    ```

!!! note "Runtime-only Installation"
    If you only need runtime dependencies (e.g., for production):
    ```bash
    make install
    ```

### Initialize the Database

Run migrations to set up the database schema:

```bash
make upgrade
```

### Run the API Server

```bash
make api
```

The API server starts at http://localhost:5000 with:

- Auto-reload on code changes
- Debug mode enabled
- Flask debugger active

### Run the Worker

In a separate terminal:

```bash
make worker
```

The worker processes background tasks like:

- Document ingestion
- Entity extraction
- Cross-referencing
- Index updates

## 5. Frontend Setup

### Install Node Dependencies

```bash
make dev-ui
# or
cd ui && npm install
```

### Run the Development Server

```bash
make ui
# or
cd ui && npm start
```

The UI development server starts at http://localhost:3000 with:

- Hot module replacement
- Proxy to backend API
- Source maps for debugging

## 6. Verify the Setup

1. Open http://localhost:3000 in your browser
2. You should see the Aleph homepage
3. In single-user mode, you're automatically logged in

## Common Commands

| Command | Description |
|---------|-------------|
| `make services` | Start Docker services |
| `make stop` | Stop Docker services |
| `make api` | Run API server locally |
| `make worker` | Run background worker locally |
| `make ui` | Run UI development server |
| `make test` | Run backend tests |
| `make lint` | Run Python linter |
| `make format` | Format Python code |
| `make tail` | Follow Docker service logs |

## Troubleshooting

### Elasticsearch fails to start

Elasticsearch requires increased virtual memory. On Linux:

```bash
sudo sysctl -w vm.max_map_count=262144
```

To make it permanent, add to `/etc/sysctl.conf`:

```
vm.max_map_count=262144
```

### Database connection refused

Ensure PostgreSQL is running and healthy:

```bash
docker compose ps postgres
docker compose logs postgres
```

### Port already in use

Check what's using the port and stop it:

```bash
# Find process using port 5000
lsof -i :5000

# Or use a different port
FLASK_RUN_PORT=5001 make api
```

### Permission issues with Docker volumes

On Linux, you may need to fix volume permissions:

```bash
sudo chown -R $USER:$USER data/
```
