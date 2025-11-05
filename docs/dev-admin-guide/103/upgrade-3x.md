# Upgrading from Aleph 3.x to OpenAleph 5

This guide covers the upgrade process from Aleph 3.x to OpenAleph 5, including breaking changes, migration steps, and configuration updates.

!!! info "Coming from pre 5"
    Directly upgrade to OpenAleph 5.1 and skip the 5.0.x versions

## Prerequisites

### Minimum Requirements

- **PostgreSQL**: Version 13 or later (previously version 10). Upgrade first.
- **Elasticsearch**: Version 9 or later. Existing clusters upgrade works straight forward, refer to their documentation.

### Pre-Upgrade Checklist

1. Back up your PostgreSQL database
2. Review the breaking changes section below
3. Plan for downtime during reindexing operations or configure rollover (see below).
4. Ensure sufficient disk space for new indices

## Breaking Changes in OpenAleph 5

### Task Queue System

- Completely reworked task queue using [Procrastinate](https://procrastinate.readthedocs.io/en/stable/). This means Redis and RabbitMQ (Aleph v. 4) are not used as a task queue anymore.
- Requires database migrations via `aleph upgrade` command
- Requires PostgreSQL 13+
- New worker service architecture (`ingest-file` and `analyze`)

[Technical background and documentation](https://openaleph.org/docs/lib/openaleph-procrastinate/)

### Elasticsearch Index Structure

Refactored index structure and mappings: Not one index per entity schema anymore but less indices for groups of entity schemata.

Entities are now organized into buckets based on schema type:

| Bucket | Schemas | Purpose |
|--------|---------|---------|
| `things` | [Thing and descendants](https://followthemoney.tech/explorer/schemata/Thing/) | Entities ([Person](https://followthemoney.tech/explorer/schemata/Person/), [Company](https://followthemoney.tech/explorer/schemata/Company/), ...) |
| `intervals` | [Interval and descendants](https://followthemoney.tech/explorer/schemata/Interval/) | Time-based entity connections ([Ownership](https://followthemoney.tech/explorer/schemata/Ownership/), [Sanction](https://followthemoney.tech/explorer/schemata/Sanction/), ...) |
| `documents` | [Document and descendants](https://followthemoney.tech/explorer/schemata/Document/) | File-like entities with full-text |
| `pages` | [Pages](https://followthemoney.tech/explorer/schemata/Pages/) | Multi-page (Word/PDF) documents with full-text |
| `page` | [Page](https://followthemoney.tech/explorer/schemata/Page/) | Single page entities (children of `Pages`) for page-level lookups |

Index names follow the pattern: `{prefix}-entity-{bucket}-{version}`

Example: `openaleph-entity-things-v1`

[Technical documentation for openaleph-search](https://openaleph.org/docs/lib/openaleph-search/)

### Environment Variables

The following environment variables have been renamed. Legacy names still work but should be updated:

| Legacy Variable | New Variable | Notes |
|----------------|--------------|-------|
| `ALEPH_DATABASE_URI` | `OPENALEPH_DB_URI` | Main database connection |
| `FTM_STORE_URI` | `FTM_FRAGMENTS_URI` | FTM fragments storage |
| `ALEPH_ELASTICSEARCH_URI` | `OPENALEPH_ELASTICSEARCH_URI` | Elasticsearch connection |

### New Environment Variables

- `PROCRASTINATE_DB_URI` - Database URI for task queue (falls back to `OPENALEPH_DB_URI`)

## Service Architecture Changes

Introduction: [Services overview](../102/services.md)

### New Services

The worker service has been split into multiple specialized services:

- **`ingest`** - Handles file ingestion (known as `ingest-file`) - [Documentation](https://openaleph.org/docs/lib/ingest-file/)
- **`analyze`** - Handles entity analysis and NER (previously part of `ingest-file`) - [Documentation](https://openaleph.org/docs/lib/ftm-analyze/)
- **`worker`** - General task worker using Procrastinate (replaces old Aleph worker) - [Documentation](https://openaleph.org/docs/lib/openaleph-procrastinate/)

### Service Configuration

#### Ingest Service

Required environment variables:


```bash
PROCRASTINATE_DB_URI=postgresql://user:pass@db:5432/aleph
FTM_FRAGMENTS_URI=postgresql://user:pass@db:5432/aleph
ARCHIVE_PATH=/data/archive  # Or other storage configuration
```

#### Analyze Service

Required environment variables:


```bash
PROCRASTINATE_DB_URI=postgresql://user:pass@db:5432/aleph
FTM_FRAGMENTS_URI=postgresql://user:pass@db:5432/aleph
```

#### Worker Service

Required environment variables:


```bash
OPENALEPH_DB_URI=postgresql://user:pass@db:5432/aleph
PROCRASTINATE_DB_URI=postgresql://user:pass@db:5432/aleph
FTM_FRAGMENTS_URI=postgresql://user:pass@db:5432/aleph
ARCHIVE_PATH=/data/archive  # Or other storage configuration
OPENALEPH_ELASTICSEARCH_URI=http://elasticsearch:9200
```

#### API Service

Required environment variables:

- All variables from worker service
- Additional UI/app-specific settings (see [Configuration Reference](../102/configuration.md))

## Upgrade Procedure

### Step 1: Upgrade PostgreSQL

If your PostgreSQL version is below 13, upgrade it first before proceeding.

**Current recommendation**: PostgreSQL 18 (latest stable)

Refer to PostgreSQL documentation for upgrade procedures specific to your deployment method.

### Step 2: Update Docker Services and Configuration

!!! info "Rolling upgrade"
    If you can't afford any downtime, keep your existing pre-5 instance running and deploy the new procrastinate worker service (no ingest and analyze needed) separately. Configure it with the required database and elasticsearch connections and start the [rollover reindex](./reindex.md) from this container. Scale it to have parallel reindex throughput. Once the re-index is done, continue with updating the full docker stack as described below.

Update your docker setup to include the new service definitions and configurations. Refer to the [example `docker-compose.yml`](../102/docker.md) as a reference.

**Note**: If you use a single database for application data, FollowTheMoney data and the task queue, set `FTM_FRAGMENTS_URI` and `PROCRASTINATE_DB_URI` to the same value as `OPENALEPH_DB_URI`. ([See the PostgreSQL section in services](../102/services.md))

### Step 3: Run Database Migrations

Execute the upgrade command in a running Aleph container:

```bash
aleph upgrade
```

This command will:

- Run database migrations
- Create Procrastinate task queue tables
- Set up new index configurations

### Step 4: Reindexing

[OpenAleph reindexing](./reindex.md)

#### Index Storage Considerations

The new index structure stores additional information for improved search capabilities, including:

- Enhanced person and company name data
- Full-text content for proper highlighting on the `content` field (was not stored in 3.x and 4.x versions)

**Expected storage increase**: Varies based on data composition. Instances with full-text indexing already enabled in 3.x will see moderate growth. Instances without full-text indexing will see larger increases.

#### If storage size is a serious concern

Per default, _term vectors with offsets_ where always indexed in prior Aleph versions, so we kept it. But it is not necessary and can reduce storage about 20% (if the data contains a lot of full text).

```bash
OPENALEPH_SEARCH_CONTENT_TERM_VECTORS=0  # disable term vectors
OPENALEPH_SEARCH_HIGHLIGHTER_FVH_ENABLED=0  # can't use FVH then
```
[More at openaleph-search documentation](https://openaleph.org/docs/lib/openaleph-search/reference/settings/#content_term_vectors)

## Running Commands

All `aleph` commands must be executed inside a running Aleph container (worker or api) with correct environment variables configured.

### Docker Compose

```bash
docker-compose run --rm api aleph <command>
```

### Direct Container Exec

```bash
docker exec -it <container-name> aleph <command>
```

## See Also

- [Configuration Reference](../102/configuration.md) - All configuration parameters
- [Services Architecture](../102/services.md) - Understanding service components
- [Upgrading from 4.x](upgrade-4x.md) - Notes for 4.x users
- [Version History](versions.md) - Release notes and changelog

## Need help?

[Join our discourse](https://darc.social) to ask for any specific help with reindexing or other OpenAleph operations.
