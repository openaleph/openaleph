# OpenAleph Versions

[github.com/openaleph/openaleph](https://github.com/openaleph/openaleph)

OpenAleph is the actively developed and maintained open source fork of it's discontinued predecessor, [Aleph](https://github.com/alephdata/aleph/).

## 5.x

The current versions for OpenAleph, forked off from the 3.x branch (see below)

### 5.1.0

Released: 2025-11-07

If upgrading from 5.0.x to 5.1.0, a [reindex](./reindex.md) is still required due to:

- Reduced Elasticsearch ingest and analysis pipeline complexity introduced in 5.0
- New dedicated `Page` index for document pages

### 5.0.0

Released: 2025-09-01

Requires [reindexing](./reindex.md) and upgrading configuration, see [upgrading from 3.x](./upgrade-3x.md) or [upgrading from 4.x](./upgrade-4x.md).

## 4.x

This (discontinued) version line was developed by the original maintainer (OCCRP) and introduced RabbitMQ as a task queue. Upgrading from this version might require manual database migration fixes, [see migration notes](./upgrade-4x.md).

## 3.x

OpenAleph was forked off from the 3.17 Aleph version. Upgrades from this versions to 5.x is straight forward.
