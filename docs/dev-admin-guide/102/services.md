# Services

The OpenAleph stack consists of several services for data storage, search index and application logic.

!!! info "PostgreSQL and Elasticsearch"
    Though the example `docker-compose.yml` lists PostgreSQL and Elasticsearch as docker services, we recommend running these outside docker ("bare metal") as services on different machines.

## Source documents

This component is referred to as **Archive** in various documentation sections and in the codebase. Currently, the Archive can be one of:

- Local filesystem
- S3-compatible blob storage
- Google Cloud Storage

In the future (OpenAleph 6), more backends might be supported, for instance Azure Blob Storage.

OpenAleph stores source files via their `sha1`-checksums in the key prefix format `aa/bb/cc/aabbcc123456.../data`

## Database(s) – PostgreSQL

OpenAleph uses PostgreSQL (yes, only PostgreSQL or compatible engines supported) for three purposes. This can be all in one database or three different database deployments for high performance deployments. In that case, the different database servers can be configured and resource optimized for the specific usage pattern.

If you plan to only use one database for all purposes (suitable for small to mid sized OpenAleph instances), just use `OPENALEPH_DB_URI` as the configuration variable.

Minimum PostgreSQL version is 13, we recommend the latest (which is currently 17).

### Application data

Stores User, Groups, Permissions, Collection metadata. This is usually not a big database, except the so called `documents` table. This stores meta information about all documents ever uploaded to OpenAleph. This table can grow over time and become slow when iterating or sorting the entire table.

Setting: `OPENALEPH_DB_URI`

### Entities data

This database stores all entity data in [FollowTheMoney](https://followthemoney.tech) json format. It has one table per collection (dataset). This is the _source of truth_ for Elasticsearch, all (re-)indexing reads from this store. This database can grow into many Terrabytes depending on your data.

Setting: `FTM_FRAGMENTS_URI`

### Task queue data

This database holds the jobs data for the worker queues. Expect heavy reads and writes when running many workers. This can become the bottleneck when running large scale processing deployments and benefits from more resources and postgresql-specific optimizations.

The underlying task queue framework is [procrastinate](https://procrastinate.readthedocs.io/en/stable/).

Setting: `PROCRASTINATE_DB_URI`

## Search Index - Elasticsearch

OpenAleph uses Elasticsearch to provide keyword and full-text search. See [openaleph-search](https://openaleph.org/docs/lib/openaleph-search/) technical documentation. Operating an Elasticsearch Cluster is out of scope for this documentation, but many tweaks and optimizations can be helpful or even necessary depending on the nature of your source data and usage patterns. As the database holds all the entity data (see above), the complete Index can always re-created from the database.

Minimum Elasticsearch version is 9. OpenAleph uses the [ICU Analysis plugin](https://www.elastic.co/docs/reference/elasticsearch/plugins/analysis-icu) for full-text processing. Refer to the documentation for how to install it. There is a pre-build docker container with the plugin available at [ghcr.io/openaleph/elasticsearch](https://github.com/openaleph/openaleph-search/pkgs/container/elasticsearch)

Setting: `OPENALEPH_ELASTICSEARCH_URI`

The setting variable can either point to one Elasticsearch node or to a json-formatted list of multiple nodes that will be used round-robin.

## Cache - Redis

OpenAleph uses a cache layer that doesn't need to be persistent. The application is expecting the redis api.

Setting: `REDIS_URL`

## Ingest File Worker

Worker service to ingest and process source files. The more replicas are deployed, the faster OpenAleph can ingest files.

Image: `ghcr.io/openaleph/ingest-file`

Run command: `procrastinate worker -q ingest`

[Documentation](https://openaleph.org/docs/lib/ingest-file/)

Dependencies:

- Archive
- FollowTheMoney Database
- Task queue Database
- Redis (though it can use it's own instance as no cache is shared with other parts of the stack)

## Analyze Worker

Worker service to analyze ingested documents (NER tagging and other extractions).

Image: `ghcr.io/openaleph/ftm-analyze`

Run command: `procrastinate worker -q analyze`

[Documentation](https://openaleph.org/docs/lib/ftm-analyze/)

Dependencies:

- FollowTheMoney Database
- Task queue Database

## Application Worker

Worker service to process application related tasks, including triggering ingest and analyze tasks as well as maintenance tasks. User-triggered actions like (re-)indexing or updating entities are handled by these workers, too.

Image: `ghcr.io/openaleph/openaleph`

Run command: `procrastinate worker -q openaleph`

Dependencies:

- Application Database
- FollowTheMoney Database
- Task queue Database
- Redis cache
- Elasticsearch

### Considerations

For small deployments, 2-3 workers might be sufficient. Deploy more for large scale deployments. It can be a good idea to separate different tasks to different worker services. For instance having dedicated _snappy_ workers for user-triggered tasks and _background_ workers for long running tasks. Refer to the [openaleph-procrastinate](https://openaleph.org/docs/lib/openaleph-procrastinate/) documentation for how to configure different queues for different tasks so that different workers can be deployed listening to specific queues.

## Api Service

Image: `ghcr.io/openaleph/openaleph`

Run command: `gunicorn --config /aleph/gunicorn.conf.py --workers 6`

Dependencies:

- Application Database
- FollowTheMoney Database
- Task queue Database
- Redis cache
- Elasticsearch
- Archive

Exposes the Flask-powered python api the UI is talking to. Scale as needed.

## UI (Frontend)

This just serves the static assets and React router App. All other requests are passed through the api service.

Image: `ghcr.io/openaleph/aleph-ui`

Run command: `nginx`

Dependencies: None, or api service if using default pass through.

Recommendation: Per default, a reverse proxy would forward requests to only this service. But you can as well expose the Api services directly to the reverse proxy to handle all `/api/...` path requests directly.
