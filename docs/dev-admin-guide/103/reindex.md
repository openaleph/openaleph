# Re-indexing OpenAleph

Version upgrades, most notably major bumps, usually require re-indexing the data. This is intended to continuously provide new and innovative features that can introduce breaking changes.

We know that reindexing a big Aleph instance isn't convenient and that's why it was avoided in previous versions to introduce breaking changes on the index. But we realized to move forward in adding new features, reindexing can't be a blocker. That's why we worked on the indexing module to be multi-threaded which speeds up the re-indexing. As well, reindexing will happen in the future more often and we are actively working on making it as fast and efficient as possible, so that it is not a blocker anymore.

We are indexing more information now, most notably about person and company names. We acknowledge that storage is always an issue and there has always been the tendency to keep the Aleph index size at its minimum to save storage costs at the cost of features (e.g., highlighting for documents, improved name-matching), but we decide that **if you want to find things, you need to index them**.

## Benchmark

The reindexing is parallelized and can be as fast as resources available.

On [search.openaleph.org](https://search.openaleph.org) we can re-index several TB within one day. On our managed [DARC](https://darc.li) deployments we have seen throughput of 40.000 entity docs / second. More full-text requires more computation time for Elasticsearch, as the ICU analysis is heavy.

It is hard to predict as many factors impact the speed for reindexing, but a rule of thumb is that an OpenAleph instance with less than 1 TB of index data can be reindexed within 24h.

The bottleneck is usually not Elasticsearch or the indexing logic, but the underlying database (FTM Store, see [Services](../102/services.md)) as reindexing needs to do a full sort table scan per collection. This will completely refactored and improved in upcoming OpenAleph 6.

## Prerequisites

Before starting a reindexing operation:

1. Ensure Elasticsearch cluster runs at version 9. Refer to their documentation on how to upgrade. Upgrading existing OpenAleph data clusters from prior versions works straight forward. But of course make sure you have a backup of the PostgreSQL database that holds the source FollowTheMoney data (see [Services](../102/services.md) and [Backup](../102/backup.md)).
2. Ensure sufficient disk space for new indices if using rollover approach (see below)
3. Plan for downtime or read-only mode during the process
4. Review performance tuning settings for your deployment size

## Reindexing Procedure

### Step 1: Enable Maintenance Mode

Set your instance into maintenance mode to disallow user edits and prevent data modifications during reindexing:

```bash
ALEPH_MAINTENANCE=1
ALEPH_APP_BANNER="System maintenance in progress. Re-indexing data."
```

This ensures data consistency during the reindexing process.

### Step 2: Configure PostgreSQL Settings

Ensure PostgreSQL has no or a very high `idle_in_transaction_session_timeout` setting (e.g., 24 hours). This prevents timeout failures during large collection iterations:

```sql
-- In PostgreSQL configuration or per-session
SET idle_in_transaction_session_timeout = '24h';
```

The PostgreSQL `FETCH` operation in the FTM store is a transaction even when only reading, and long reindexing tasks can timeout if this setting is too low.

### Step 3: Optimize Elasticsearch Settings

Configure the Elasticsearch refresh interval to reduce overhead during bulk indexing. Set it to a high value or disable it entirely:

```bash
# Disable refresh during reindexing (recommended)
curl -X PUT "http://elasticsearch:9200/openaleph-*/_settings" -H 'Content-Type: application/json' -d'
{
  "index": {
    "refresh_interval": "-1"
  }
}
'

# Or set to 1 hour
curl -X PUT "http://elasticsearch:9200/openaleph-*/_settings" -H 'Content-Type: application/json' -d'
{
  "index": {
    "refresh_interval": "1h"
  }
}
'
```

Remember to reset to `1s` after reindexing completes to restore search responsiveness.

### Step 4: Configure Performance Settings

Adjust indexing performance settings based on your cluster resources:

```bash
# Connection settings
OPENALEPH_ELASTICSEARCH_URI=["http://es-1:9200","http://es-2:9200"]

# Indexing performance (adjust based on your cluster)
OPENALEPH_SEARCH_INDEXER_CONCURRENCY=8
OPENALEPH_SEARCH_INDEXER_MAX_CHUNK_BYTES=10485760  # 10 MB
OPENALEPH_SEARCH_INDEXER_CHUNK_SIZE=1000
```

Deploy a reasonable number of worker instances to process reindexing tasks in parallel.

### Step 5: Reset or Prepare Indices

Choose one of the following approaches:

#### Option A: Reset Indices (Clean Reindex)

Reset the index completely. **Warning: This deletes all current data!**

```bash
openaleph-search reset
```

#### Option B: Rollover Reindex (Zero-Downtime)

Configure a new index version to reindex while keeping the old indices available for search:

```bash
# Set new write index version
OPENALEPH_SEARCH_INDEX_WRITE=v2

# Old indices remain readable
OPENALEPH_SEARCH_INDEX_READ=v1
```

### Step 6: Run Reindexing

Choose the appropriate reindexing method for your use case:

#### Asynchronous Reindexing (Recommended for Production)

Queue all reindexing tasks to be processed by workers in parallel:

```bash
aleph reindex-full --queue --queue-batches
```

This creates multiple tasks for 10,000 entity batches that workers will consume in parallel. Monitor progress via:

- Worker logs
- OpenAleph Status dashboard
- Database task queue

#### Synchronous Reindexing (For Development or Debugging)

Reindex collections sequentially with visible log output in one process (use tmux or something to keep it running):

```bash
aleph reindex-full
```

This method is slower but provides immediate feedback and is useful for troubleshooting.

### Step 7: Monitor Progress

Track reindexing progress through:

- Worker service logs
- Status dashboard
- Elasticsearch cluster health and indexing metrics
- Task queue status in PostgreSQL

### Step 8: Post-Reindex Cleanup

Once reindexing completes successfully:

1. Reset Elasticsearch refresh interval

```bash
curl -X PUT "http://elasticsearch:9200/openaleph-*/_settings" -H 'Content-Type: application/json' -d'
{
  "index": {
    "refresh_interval": "1s"
  }
}
'
```

2. Disable maintenance mode

```bash
ALEPH_MAINTENANCE=0
# Remove ALEPH_APP_BANNER or update it
```

3. Verify indices are working correctly

- Test search functionality
- Check entity retrieval
- Verify collection access

4. Clean up old indices (if using rollover)

```bash
# List indices to verify old ones
curl "http://elasticsearch:9200/_cat/indices?v"

# Delete old indices after verification. On default, Elasticsearch doesn't allow
# wildcard delete, so run this command for each index:
curl -X DELETE "http://elasticsearch:9200/openaleph-entity-{schema}-{v}"
```

## Running Commands

All `aleph` and `openaleph-search` commands must be executed inside a running Aleph container (worker or api) with correct environment variables configured.

### Docker Compose

```bash
docker-compose run --rm api aleph reindex-full --queue --queue-batches
```

### Direct Container Exec

```bash
docker exec -it <container-name> aleph reindex-full --queue --queue-batches
```

## See Also

- [Upgrading from 3.x](upgrade-3x.md) - Complete upgrade guide
- [Upgrading from 4.x](upgrade-4x.md) - Version-specific upgrade notes
- [Configuration Reference](../102/configuration.md) - All configuration parameters
- [Services Architecture](../102/services.md) - Understanding service components

## Troubleshooting, Help?

[Join our discourse](https://darc.social) to ask for any specific help with reindexing or other OpenAleph operations.
