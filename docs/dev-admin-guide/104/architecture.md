# Architecture Overview

This document describes the high-level architecture of Aleph for developers. For detailed service descriptions, see the [Services Overview](../102/services.md).

## External dependencies

Some parts of the logic are extracted into other libraries:

### Core logic

- [`openaleph-procrastinate`](https://openaleph.org/docs/lib/openaleph-procrastinate/) Task queue implementation
- [`openaleph-search`](https://openaleph.org/docs/lib/openaleph-search/) Elasticsearch mappings, indexer and query logic

### Processing services

- [`ingest-file`](https://openaleph.org/docs/lib/ingest-file/) Stage 1 of document processing (import, extract metadata & text, OCR)
- [`ftm-analyze`](https://openaleph.org/docs/lib/ftm-analyze/) Stage 2 of document processing (NER, language detection and other analysis)

## Components

```mermaid
flowchart TB
    subgraph Client
        Browser[Browser]
    end

    subgraph Frontend
        UI[UI / nginx]
    end

    subgraph Backend
        API[API / Flask]
        Worker[Application Worker]
    end

    subgraph Processing
        Ingest[ingest-file Worker]
        Analyze[ftm-analyze Worker]
    end

    subgraph Storage
        PG[(PostgreSQL)]
        ES[(Elasticsearch)]
        Redis[(Redis)]
        Archive[(Archive / S3)]
    end

    Browser --> UI
    UI --> API
    API --> PG
    API --> ES
    API --> Redis
    API --> Archive
    Worker --> PG
    Worker --> ES
    Ingest --> PG
    Ingest --> Archive
    Analyze --> PG
```

## Data Stores

### PostgreSQL

PostgreSQL serves three distinct purposes (can be separate databases for large deployments):

| Purpose | Setting | Description |
|---------|---------|-------------|
| **Application data** | `OPENALEPH_DB_URI` | Users, groups, permissions, collection metadata |
| **Entities data** | `FTM_FRAGMENTS_URI` | FollowTheMoney entities (source of truth for search index) |
| **Task queue** | `PROCRASTINATE_DB_URI` | Job data for [Procrastinate](https://procrastinate.readthedocs.io/) workers |

### Elasticsearch

Full-text and keyword search index. Can be rebuilt from PostgreSQL entity data at any time.

- Setting: `OPENALEPH_ELASTICSEARCH_URI`
- Requires ICU Analysis plugin

### Redis

Application caching layer only. Not used for task queues.

- Setting: `REDIS_URL`
- Does not need to be persistent

### Archive

Source document storage (PDFs, images, etc.) addressed by SHA1 checksum.

- Setting: `ARCHIVE_TYPE` and `ARCHIVE_PATH` (or S3/GCS settings)
- Supports: local filesystem, S3, Google Cloud Storage

## Task Processing

Aleph uses [Procrastinate](https://procrastinate.readthedocs.io/) for background task processing. Tasks are stored in PostgreSQL and processed by workers.

```mermaid
flowchart LR
    subgraph Queues[PostgreSQL Task Queues]
        Q1[openaleph]
        Q2[openaleph-management]
        Q3[ingest]
        Q4[analyze]
    end

    subgraph Workers
        W1[Application Worker]
        W2[ingest-file]
        W3[ftm-analyze]
    end

    Q1 --> W1
    Q2 --> W1
    Q3 --> W2
    Q4 --> W3
```

| Queue | Worker | Purpose |
|-------|--------|---------|
| `openaleph` | Application Worker | Indexing, cross-referencing, entity updates |
| `openaleph-management` | Application Worker | Administrative tasks |
| `ingest` | ingest-file | Document processing, text extraction, OCR |
| `analyze` | ftm-analyze | Named entity recognition, language detection |

## Data Flow

### Document Ingestion

```mermaid
sequenceDiagram
    participant User
    participant API
    participant Archive
    participant PG as PostgreSQL
    participant Ingest as ingest-file
    participant Analyze as ftm-analyze
    participant Worker as App Worker
    participant ES as Elasticsearch

    User->>API: Upload document
    API->>Archive: Store file
    API->>PG: Create entity + queue task
    PG->>Ingest: Process (ingest queue)
    Ingest->>Archive: Read file
    Ingest->>PG: Extract text + queue analyze
    PG->>Analyze: Analyze (analyze queue)
    Analyze->>PG: Extract entities + queue index
    PG->>Worker: Index (openaleph queue)
    Worker->>ES: Update search index
```

### Search

```mermaid
sequenceDiagram
    participant User
    participant UI
    participant API
    participant ES as Elasticsearch

    User->>UI: Enter search query
    UI->>API: GET /api/2/entities?q=...
    API->>ES: Query with filters
    ES->>API: Results with highlights
    API->>UI: JSON response
    UI->>User: Render results
```

## Code Structure

### Backend (`aleph/`)

```
aleph/
├── views/          # API endpoints (Flask blueprints)
├── logic/          # Business logic
├── model/          # SQLAlchemy models
├── queues/         # Procrastinate task definitions
├── index/          # Elasticsearch indexing
└── migrate/        # Database migrations
```

### Frontend (`ui/src/`)

```
ui/src/
├── components/     # Reusable React components
├── screens/        # Page-level components
├── actions/        # Redux actions
├── reducers/       # Redux reducers
├── selectors/      # Redux selectors
└── app/            # App configuration, routing
```
