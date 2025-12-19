# Backups

The backup strategy for OpenAleph usually is a trade-off between availability on failure, recover period and backup costs (both in terms of storage costs and complexity / runtime).

## Minimal Backup

- Archive (source files)
- PostgreSQL

That's it, the Elasticsearch Index is completely recoverable from the PostgreSQL database.

## To consider for production

For high-availablity deployments, consider:

- Archive storage bucket replication
- PostgreSQL replication
- Elasticsearch replication

Then the application can fail-over quickly to the replica services while restoring or recovering backups.
