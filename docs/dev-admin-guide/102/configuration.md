# Configuration Reference

This document provides a comprehensive reference for all configuration parameters available in OpenAleph. Configuration is managed through environment variables that override default values defined in `aleph/settings.py`.

## General Guidelines

- Never edit `aleph/settings.py` directly for deployment
- Use environment variables to override defaults
- All environment variables are prefixed with `ALEPH_` or `OPENALEPH_`
- Boolean values: `true`, `yes`, `1` (case-insensitive) evaluate to True
- List values: Comma-separated by default, or use custom separator

---

## Application Behavior

### Debug and Development

#### `ALEPH_DEBUG`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Enables debug mode, showing detailed error messages to users. Should be disabled in production.

#### `ALEPH_PROFILE`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Enables request profiling for performance analysis.

#### `ALEPH_CACHE`
- **Type**: Boolean
- **Default**: `true` (except when `ALEPH_DEBUG=true`)
- **Description**: Proposes HTTP caching to user agents for improved performance.

#### `ALEPH_MAINTENANCE`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Puts the system into read-only mode. Use together with `ALEPH_APP_BANNER` to display a notification for users (see below).

---

## Instance Information

### Branding and Identity

#### `ALEPH_APP_TITLE`
- **Type**: String
- **Default**: `"OpenAleph"`
- **Description**: The title of your Aleph instance, displayed in the UI and browser title.

#### `ALEPH_APP_NAME`
- **Type**: String
- **Default**: `"aleph"`
- **Description**: Internal application name, used for naming conventions and identifiers.

#### `ALEPH_UI_URL`
- **Type**: String (URL)
- **Default**: `"http://localhost:8080/"`
- **Description**: The public URL where the Aleph UI is accessible. Used for generating links in emails and redirects.

#### `ALEPH_LOGO`
- **Type**: String (path or url)
- **Default**: `"/static/logo.svg"`
- **Description**: Path or URL to the main logo file displayed in the UI.

#### `ALEPH_LOGO_AR`
- **Type**: String (path or url)
- **Default**: Same as `ALEPH_LOGO`
- **Description**: Path or URL to the Arabic/RTL version of the logo.

#### `ALEPH_FAVICON`
- **Type**: String (path or url)
- **Default**: `"/static/favicon.ico"`
- **Description**: Path or URL to the favicon file.

### System Messages

#### `ALEPH_APP_BANNER`
- **Type**: String
- **Default**: None
- **Description**: Text to display as a system-wide banner in the user interface. Useful for announcements or warnings.

#### `ALEPH_APP_MESSAGES_URL`
- **Type**: String (URL)
- **Default**: None
- **Description**: URL endpoint for fetching system messages to display in the UI.

---

## Security and HTTPS

#### `ALEPH_FORCE_HTTPS`
- **Type**: Boolean
- **Default**: `true` if `ALEPH_UI_URL` starts with "https", otherwise `false`
- **Description**: Forces HTTPS for all connections. Automatically enabled when UI URL uses HTTPS.

#### `ALEPH_URL_SCHEME`
- **Type**: String
- **Default**: `"https"` if `ALEPH_FORCE_HTTPS` is true, otherwise `"http"`
- **Description**: Preferred URL scheme for generated links.

#### `ALEPH_CONTENT_POLICY`
- **Type**: String
- **Default**: `"default-src: 'self' 'unsafe-inline' 'unsafe-eval' data: *"`
- **Description**: Content Security Policy header value. Defines allowed sources for scripts, styles, and other resources.

#### `ALEPH_CORS_ORIGINS`
- **Type**: List (pipe-separated)
- **Default**: `["*"]`
- **Separator**: `|`
- **Description**: Cross-Origin Resource Sharing (CORS) allowed origins. Use pipe character to separate multiple origins (e.g., `http://localhost:3000|https://example.com`).

---

## Authentication and Authorization

### Core Security

#### `ALEPH_SECRET_KEY`
- **Type**: String
- **Default**: None
- **Required**: Yes
- **Description**: Secret key for cryptographic operations, session signing, and token generation. **Must be set to a random, secure value in production.**

#### `ALEPH_ADMINS`
- **Type**: List (comma-separated)
- **Default**: Empty list
- **Description**: Email addresses of users who should automatically be designated as administrators.
- **Example**: `admin@example.com,superuser@example.com`

#### `ALEPH_SYSTEM_USER`
- **Type**: String
- **Default**: `"system:aleph"`
- **Description**: Foreign ID of the default system user for automated operations.

### OAuth/OIDC Configuration

#### `ALEPH_OAUTH`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Enables OAuth/OIDC authentication.

#### `ALEPH_OAUTH_HANDLER`
- **Type**: String
- **Default**: `"oidc"`
- **Options**: `oidc`, `keycloak`, `google`, `cognito`, `azure`, or custom plugin
- **Description**: OAuth provider handler type.

#### `ALEPH_OAUTH_KEY`
- **Type**: String
- **Default**: None
- **Description**: OAuth client ID provided by your identity provider.

#### `ALEPH_OAUTH_SECRET`
- **Type**: String
- **Default**: None
- **Description**: OAuth client secret provided by your identity provider.

#### `ALEPH_OAUTH_SCOPE`
- **Type**: String
- **Default**: `"openid email profile"`
- **Description**: OAuth scopes to request from the identity provider.

#### `ALEPH_OAUTH_AUDIENCE`
- **Type**: String
- **Default**: None
- **Description**: OAuth audience parameter, required by some identity providers.

#### `ALEPH_OAUTH_METADATA_URL`
- **Type**: String (URL)
- **Default**: None
- **Description**: URL to the OAuth provider's OIDC discovery/metadata endpoint (e.g., `.well-known/openid-configuration`).

#### `ALEPH_OAUTH_TOKEN_METHOD`
- **Type**: String
- **Default**: `"POST"`
- **Description**: HTTP method for token exchange requests.

#### `ALEPH_OAUTH_ADMIN_GROUP`
- **Type**: String
- **Default**: `"superuser"`
- **Description**: Name of the OAuth group whose members should be granted admin privileges.

#### `ALEPH_OAUTH_MIGRATE_SUB`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Enables migration of OAuth subject identifiers for backward compatibility.

### Authentication Modes

#### `ALEPH_SINGLE_USER`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Disables authentication completely. Everyone accessing the system is treated as an administrator. **Use only for local development.**

#### `ALEPH_REQUIRE_LOGGED_IN`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Requires authentication for all access. Disables anonymous browsing.

#### `ALEPH_PASSWORD_LOGIN`
- **Type**: Boolean
- **Default**: `true` if OAuth is disabled, otherwise `false`
- **Description**: Enables password-based authentication. Typically disabled when using SSO/OAuth.

### Session Management

#### `ALEPH_SESSION_EXPIRE`
- **Type**: Integer (seconds)
- **Default**: `800,000` (222 hours) in single-user mode, `60,000` (16.7 hours) otherwise
- **Description**: Session duration before automatic logout.

#### `ALEPH_ROLE_INACTIVE`
- **Type**: Integer (days)
- **Default**: `180` (6 months)
- **Description**: Users who haven't logged in for this many days will stop receiving notifications.

#### `ALEPH_NOTIFICATIONS_DELETE`
- **Type**: Integer (days)
- **Default**: `90` (3 months)
- **Description**: Notifications older than this are automatically deleted.

---

## Content and Localization

### Language Settings

#### `ALEPH_DEFAULT_LANGUAGE`
- **Type**: String
- **Default**: `"en"`
- **Description**: Default language code for content processing and UI.

#### `ALEPH_UI_LANGUAGES`
- **Type**: List (comma-separated)
- **Default**: `["ru", "es", "de", "en", "ar", "fr"]`
- **Description**: Languages available in the user interface.

### Search and Display

#### `ALEPH_RESULT_HIGHLIGHT`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Enables highlighting of search terms in results.

#### `ALEPH_MAX_EXPAND_ENTITIES`
- **Type**: Integer
- **Default**: `200`
- **Description**: Maximum number of entities to return per property when expanding entity relationships.

### Rate Limiting

#### `ALEPH_API_RATE_LIMIT`
- **Type**: Integer (requests per minute)
- **Default**: `30`
- **Description**: Maximum API requests per minute for anonymous users. The rate window is fixed at 15 minutes.

### Export Limits

#### `EXPORT_MAX_SIZE`
- **Type**: Integer (bytes)
- **Default**: `1073741824` (1 GB)
- **Description**: Maximum file size for exports.

#### `EXPORT_MAX_RESULTS`
- **Type**: Integer
- **Default**: `100,000`
- **Description**: Maximum number of search results that can be exported.

### Content Management

#### `ALEPH_PAGES_PATH`
- **Type**: String (path)
- **Default**: `<aleph_dir>/pages`
- **Description**: Directory path for mini-CMS pages content.

---

## Email Configuration

#### `ALEPH_MAIL_FROM`
- **Type**: String (email)
- **Default**: `"aleph@domain.com"`
- **Description**: Sender email address for outgoing emails.

#### `ALEPH_MAIL_HOST`
- **Type**: String (hostname)
- **Default**: `"localhost"`
- **Description**: SMTP server hostname.

#### `ALEPH_MAIL_USERNAME`
- **Type**: String
- **Default**: None
- **Description**: Username for SMTP authentication.

#### `ALEPH_MAIL_PASSWORD`
- **Type**: String
- **Default**: None
- **Description**: Password for SMTP authentication.

#### `ALEPH_MAIL_SSL`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Use SSL encryption for SMTP connection.

#### `ALEPH_MAIL_TLS`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Use TLS encryption for SMTP connection.

#### `ALEPH_MAIL_PORT`
- **Type**: Integer
- **Default**: `465`
- **Description**: SMTP server port number.

#### `ALEPH_MAIL_DEBUG`
- **Type**: Boolean
- **Default**: Same as `ALEPH_DEBUG`
- **Description**: Enables debug logging for email operations.

---

## Database Configuration

### Connection

#### `OPENALEPH_DB_URI` / `ALEPH_DATABASE_URI`
- **Type**: String (URI)
- **Default**: None
- **Required**: Yes
- **Description**: PostgreSQL database connection URI. Format: `postgresql://user:password@host:port/database`
- **Note**: `OPENALEPH_DB_URI` takes precedence over `ALEPH_DATABASE_URI`.

### Connection Pool

#### `ALEPH_SQLALCHEMY_POOL_SIZE`
- **Type**: Integer
- **Default**: `5`
- **Description**: Maximum number of permanent connections in the connection pool.

#### `ALEPH_SQLALCHEMY_POOL_RECYCLE`
- **Type**: Integer (seconds)
- **Default**: `3600` (1 hour)
- **Description**: Time after which connections are recycled to prevent stale connections.

#### `ALEPH_SQLALCHEMY_POOL_TIMEOUT`
- **Type**: Integer (seconds)
- **Default**: `30`
- **Description**: Maximum time to wait for a connection from the pool before timing out.

---

## Search Index (Elasticsearch)

### Index Management

#### `ALEPH_INDEX_PREFIX`
- **Type**: String
- **Default**: Same as `ALEPH_APP_NAME` (typically `"aleph"`)
- **Description**: Prefix for all Elasticsearch index names. Useful for running multiple instances on the same cluster.

#### `ALEPH_INDEX_WRITE`
- **Type**: String
- **Default**: `"v1"`
- **Description**: Index version suffix for write operations. Used for blue-green deployments and migrations.

#### `ALEPH_INDEX_READ`
- **Type**: List (comma-separated)
- **Default**: Same as `ALEPH_INDEX_WRITE`
- **Description**: Index version suffixes for read operations. Can specify multiple versions for migration scenarios.

#### `ALEPH_INDEX_REPLICAS`
- **Type**: Integer
- **Default**: `0`
- **Description**: Number of replica shards. `0` means no replicas (only primary shard). `2` means 3 total copies (1 primary + 2 replicas).

### Query Configuration

#### `ALEPH_INDEX_EXPAND_CLAUSE_LIMIT`
- **Type**: Integer
- **Default**: `10`
- **Description**: Maximum number of expand clauses in Elasticsearch queries.

#### `ALEPH_INDEX_DELETE_BY_QUERY_BATCHSIZE`
- **Type**: Integer
- **Default**: `100`
- **Description**: Batch size for delete-by-query operations.

---

## Cross-Reference (XREF)

#### `ALEPH_XREF_SCROLL`
- **Type**: String (time)
- **Default**: `"5m"`
- **Description**: Scroll timeout for cross-reference queries in Elasticsearch.

#### `ALEPH_XREF_SCROLL_SIZE`
- **Type**: String (number)
- **Default**: `"1000"`
- **Description**: Number of documents to fetch per scroll request during cross-referencing.

#### `FTM_COMPARE_MODEL`
- **Type**: String
- **Default**: None
- **Description**: Machine learning model identifier for entity comparison during cross-referencing.

---

## Feature Flags

#### `ALEPH_ENABLE_EXPERIMENTAL_BOOKMARKS_FEATURE`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Enables experimental bookmarks functionality.

---

## Feedback and External URLs

#### `ALEPH_FEEDBACK_URL_DOCUMENTS`
- **Type**: String (URL)
- **Default**: None
- **Description**: URL for document feedback form or endpoint.

#### `ALEPH_FEEDBACK_URL_TIMELINES`
- **Type**: String (URL)
- **Default**: None
- **Description**: URL for timeline feedback form or endpoint.

---

## Instrumentation and Monitoring

### Error Tracking

#### `SENTRY_DSN`
- **Type**: String (DSN)
- **Default**: None
- **Description**: Sentry Data Source Name for error tracking and monitoring.

#### `SENTRY_ENVIRONMENT`
- **Type**: String
- **Default**: `""`
- **Description**: Environment name for Sentry reports (e.g., `production`, `staging`).

### Metrics

#### `PROMETHEUS_ENABLED`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Enables Prometheus metrics endpoint.

#### `PROMETHEUS_PORT`
- **Type**: Integer
- **Default**: `9100`
- **Description**: Port number for Prometheus metrics endpoint.

---

## External Services

#### `FTM_ASSETS_URL`
- **Type**: String (URL)
- **Default**: None
- **Description**: Base URL for Follow the Money (FTM) assets and resources.

---

## Advanced Configuration

### Dynamic Configuration Prefixes

#### `ALEPH_STRING_CONFIG_PREFIX`
- **Type**: String
- **Default**: None
- **Description**: Environment variable prefix for dynamically loading string configuration values. Any environment variable starting with this prefix (excluding the prefix itself) will be loaded as a settings attribute.
- **Example**: If set to `CUSTOM_`, then `CUSTOM_MY_SETTING=value` creates `settings.MY_SETTING = "value"`

#### `ALEPH_JSON_CONFIG_PREFIX`
- **Type**: String
- **Default**: None
- **Description**: Environment variable prefix for dynamically loading JSON configuration values. Values are parsed as JSON before being set.
- **Example**: If set to `JSON_`, then `JSON_MY_CONFIG='{"key": "value"}'` creates `settings.MY_CONFIG = {"key": "value"}`

---

## Internal Constants

The following settings are defined in the code but are not typically overridden:

- **`SITEMAP_FLOOR`**: `"2019-06-22"` - Minimum update date for sitemap.xml
- **`API_RATE_WINDOW`**: `15` minutes - Fixed time window for rate limiting
- **`REACT_FTM_URL`**: CDN URL for React FTM embeds
- **`PROCRASTINATE_TASKS`**: `"aleph.procrastinate.tasks"` - Python module path for task definitions
- **`SQLALCHEMY_TRACK_MODIFICATIONS`**: `false` - Disables SQLAlchemy event system for model changes

---

## OpenAleph Procrastinate

The `openaleph-procrastinate` library manages asynchronous task queue processing using Procrastinate. These settings control database connections, task queuing, and service-specific configurations.

### Core Settings

#### `OPENALEPH_INSTANCE`
- **Type**: String
- **Default**: `"openaleph"`
- **Description**: Instance identifier for this Aleph deployment.

#### `OPENALEPH_DEBUG`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Enables debug mode for Procrastinate operations.

#### `OPENALEPH_PROCRASTINATE_SYNC`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Run workers synchronously instead of asynchronously. Used during testing.

### Database Configuration

#### `OPENALEPH_DB_URI` / `ALEPH_DATABASE_URI`
- **Type**: String (URI)
- **Default**: None
- **Required**: Yes
- **Description**: PostgreSQL database connection URI for OpenAleph. Also used as fallback for Procrastinate and Fragments if not specified separately.
- **Note**: Documented in [Database Configuration](#database-configuration) section above.

#### `OPENALEPH_DB_POOL_SIZE`
- **Type**: Integer
- **Default**: `5`
- **Description**: Maximum PostgreSQL connection pool size per thread.

#### `PROCRASTINATE_DB_URI`
- **Type**: String (URI)
- **Default**: Falls back to `OPENALEPH_DB_URI` or `ALEPH_DATABASE_URI`
- **Description**: Separate database URI for Procrastinate task queue. If not set, uses the main OpenAleph database.

#### `FTM_FRAGMENTS_URI` / `FTM_STORE_URI`
- **Type**: String (URI)
- **Default**: Falls back to `OPENALEPH_DB_URI` or `ALEPH_DATABASE_URI`
- **Description**: Database URI for Follow the Money (FTM) Fragments store. Falls back to main database if not specified.

### Task Queue Services

Each service in OpenAleph has configurable queue settings. The following services are available:

- `ingest` - Document ingestion
- `analyze` - Entity analysis and NER
- `transcribe` - Audio/video transcription
- `geocode` - Geographic entity resolution
- `assets` - Asset processing
- `index` - Search index operations
- `reindex` - Bulk reindexing
- `xref` - Cross-referencing
- `load_mapping` - Loading entity mappings
- `flush_mapping` - Flushing entity mappings
- `export_search` - Search result exports
- `export_xref` - Cross-reference exports
- `update_entity` - Entity updates
- `prune_entity` - Entity cleanup
- `cancel_dataset` - Dataset cancellation

#### Service Configuration Pattern

Each service can be configured using the following environment variable pattern:

- `OPENALEPH_{SERVICE}_QUEUE` - Queue name (default varies by service)
- `OPENALEPH_{SERVICE}_TASK` - Task module path (default varies by service)
- `OPENALEPH_{SERVICE}_DEFER` - Enable deferring (default: `true`)
- `OPENALEPH_{SERVICE}_MAX_RETRIES` - Max retry attempts (default: `5`, use `-1` for infinite)
- `OPENALEPH_{SERVICE}_MIN_PRIORITY` - Minimum priority value
- `OPENALEPH_{SERVICE}_MAX_PRIORITY` - Maximum priority value

**Example**: To configure the ingestion service:

```bash
OPENALEPH_INGEST_QUEUE=high-priority-ingest
OPENALEPH_INGEST_MAX_RETRIES=10
OPENALEPH_INGEST_MIN_PRIORITY=0
OPENALEPH_INGEST_MAX_PRIORITY=100
```

---

## OpenAleph Search

The `openaleph-search` library provides Elasticsearch integration. These settings control search cluster connections, indexing behavior, and query performance.

### Connection Settings

#### `OPENALEPH_SEARCH_URI` / `OPENALEPH_ELASTICSEARCH_URI`
- **Type**: String or List of Strings (URLs)
- **Default**: `http://localhost:9200`
- **Description**: Elasticsearch server URL(s). Can specify multiple URLs for cluster deployments.
- **Example**: `http://es1:9200,http://es2:9200` or `https://search.example.com:9200`

#### `OPENALEPH_SEARCH_INGEST_URI` / `OPENALEPH_ELASTICSEARCH_INGEST_URI`
- **Type**: String or List of Strings (URLs)
- **Default**: Falls back to `OPENALEPH_SEARCH_URI`
- **Description**: Optional dedicated URI(s) for ingest operations. Useful for separating ingest traffic from search queries.

#### `OPENALEPH_SEARCH_TIMEOUT`
- **Type**: Integer (seconds)
- **Default**: `60`
- **Description**: Request timeout for Elasticsearch operations.

#### `OPENALEPH_SEARCH_MAX_RETRIES`
- **Type**: Integer
- **Default**: `3`
- **Description**: Maximum retry attempts for failed Elasticsearch requests.

#### `OPENALEPH_SEARCH_RETRY_ON_TIMEOUT`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Automatically retry requests that timeout.

#### `OPENALEPH_SEARCH_CONNECTION_POOL_LIMIT_PER_HOST`
- **Type**: Integer
- **Default**: `25`
- **Description**: Connection pool limit per host for AsyncElasticsearch client.

### Indexing Performance

#### `OPENALEPH_SEARCH_INDEXER_CONCURRENCY`
- **Type**: Integer
- **Default**: `8`
- **Description**: Number of concurrent indexing workers.

#### `OPENALEPH_SEARCH_INDEXER_CHUNK_SIZE`
- **Type**: Integer
- **Default**: `1000`
- **Description**: Number of documents per indexing batch.

#### `OPENALEPH_SEARCH_INDEXER_MAX_CHUNK_BYTES`
- **Type**: Integer (bytes)
- **Default**: `5242880` (5 MB)
- **Description**: Maximum batch size in bytes for bulk indexing operations.

### Index Structure

#### `OPENALEPH_SEARCH_INDEX_PREFIX`
- **Type**: String
- **Default**: `"openaleph"`
- **Description**: Prefix for all index names.

#### `OPENALEPH_SEARCH_INDEX_WRITE`
- **Type**: String
- **Default**: `"v1"`
- **Description**: Current write index version identifier.

#### `OPENALEPH_SEARCH_INDEX_READ`
- **Type**: String or List of Strings
- **Default**: `["v1"]`
- **Description**: Index version(s) to read from. Accepts JSON string for multiple versions.

#### `OPENALEPH_SEARCH_INDEX_SHARDS`
- **Type**: Integer
- **Default**: `10`
- **Description**: Number of primary shards per index.

#### `OPENALEPH_SEARCH_INDEX_REPLICAS`
- **Type**: Integer
- **Default**: `0`
- **Description**: Number of replica shards per index.

#### `OPENALEPH_SEARCH_INDEX_NAMESPACE_IDS`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Enable ID namespacing by dataset name to prevent collisions.

#### `OPENALEPH_SEARCH_INDEX_REFRESH_INTERVAL`
- **Type**: String (time)
- **Default**: `"1s"`
- **Description**: Elasticsearch refresh interval for near-realtime search visibility.

#### `OPENALEPH_SEARCH_INDEX_EXPAND_CLAUSE_LIMIT`
- **Type**: Integer
- **Default**: `10`
- **Description**: Maximum number of query clause expansions.

#### `OPENALEPH_SEARCH_INDEX_DELETE_BY_QUERY_BATCHSIZE`
- **Type**: Integer
- **Default**: `100`
- **Description**: Batch size for delete-by-query operations.

### Index Boosting

Control relevance scoring for different entity types:

#### `OPENALEPH_SEARCH_INDEX_BOOST_INTERVALS`
- **Type**: Integer
- **Default**: `1`
- **Description**: Score boost multiplier for interval/date entities.

#### `OPENALEPH_SEARCH_INDEX_BOOST_THINGS`
- **Type**: Integer
- **Default**: `1`
- **Description**: Score boost multiplier for Thing entities.

#### `OPENALEPH_SEARCH_INDEX_BOOST_DOCUMENTS`
- **Type**: Integer
- **Default**: `1`
- **Description**: Score boost multiplier for Document entities.

#### `OPENALEPH_SEARCH_INDEX_BOOST_PAGES`
- **Type**: Integer
- **Default**: `1`
- **Description**: Score boost multiplier for Page entities.

### Search Behavior

#### `OPENALEPH_SEARCH_QUERY_FUNCTION_SCORE`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Enable function_score wrapper for advanced scoring control.

#### `OPENALEPH_SEARCH_CONTENT_TERM_VECTORS`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Enable term vectors and offsets for the content field. Required for advanced highlighting.

### Highlighting Configuration

#### `OPENALEPH_SEARCH_HIGHLIGHTER_FVH_ENABLED`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Use Fast Vector Highlighter (FVH) for content field highlighting. Requires term vectors enabled.

#### `OPENALEPH_SEARCH_HIGHLIGHTER_FRAGMENT_SIZE`
- **Type**: Integer (characters)
- **Default**: `200`
- **Description**: Number of characters per highlight snippet.

#### `OPENALEPH_SEARCH_HIGHLIGHTER_NUMBER_OF_FRAGMENTS`
- **Type**: Integer
- **Default**: `3`
- **Description**: Maximum number of highlight snippets per document.

#### `OPENALEPH_SEARCH_HIGHLIGHTER_PHRASE_LIMIT`
- **Type**: Integer
- **Default**: `64`
- **Description**: Maximum phrases to analyze per document for highlighting.

#### `OPENALEPH_SEARCH_HIGHLIGHTER_BOUNDARY_MAX_SCAN`
- **Type**: Integer (characters)
- **Default**: `100`
- **Description**: Characters to scan when finding sentence boundaries for snippets.

#### `OPENALEPH_SEARCH_HIGHLIGHTER_NO_MATCH_SIZE`
- **Type**: Integer (characters)
- **Default**: `300`
- **Description**: Fragment size to return when no match is found.

#### `OPENALEPH_SEARCH_HIGHLIGHTER_MAX_ANALYZED_OFFSET`
- **Type**: Integer (characters)
- **Default**: `999999`
- **Description**: Maximum characters to analyze for highlighting. Limits processing for very large documents.

### Authorization

#### `OPENALEPH_SEARCH_AUTH`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Enable authorization mode for dataset-based access control in search queries.

#### `OPENALEPH_SEARCH_AUTH_FIELD`
- **Type**: String
- **Default**: `"dataset"`
- **Description**: Field name to use for authorization filtering.

---

## Ingest-File

The `ingest-file` library handles document processing and text extraction. These settings configure timeout behavior and fallback strategies.

#### `INGESTORS_CONVERT_TIMEOUT`
- **Type**: Integer (seconds)
- **Default**: `300` (5 minutes)
- **Description**: Timeout for headless LibreOffice document conversion operations. Increase for very large or complex documents.

#### `INGESTORS_TIKA_FALLBACK`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Use Apache Tika as a fallback text extraction engine when primary methods fail. Requires Tika to be installed and accessible.

---

## FTM-Analyze

The `ftm-analyze` library provides named entity recognition (NER) and language identification. These settings configure NER engines, models, and analysis behavior.

### NER Engine Selection

#### `FTM_ANALYZE_NER_ENGINE`
- **Type**: String
- **Default**: `"spacy"`
- **Options**: `spacy`, `flair`, `bert`
- **Description**: NER engine to use. Different engines may require additional dependencies.
  - `spacy` - Fast, accurate, good for production
  - `flair` - Higher accuracy, slower performance
  - `bert` - Transformer-based, best accuracy, slowest

#### `FTM_ANALYZE_NER_DEFAULT_LANG`
- **Type**: String (3-letter code)
- **Default**: `"eng"`
- **Description**: Default language for NER processing. Uses ISO 639-3 three-letter codes.

### Type Prediction Model

#### `FTM_ANALYZE_NER_TYPE_MODEL_PATH`
- **Type**: String (path)
- **Default**: `"./models/model_type_prediction.ftz"`
- **Description**: Local path to the fastText model for FTM entity type prediction.

#### `FTM_ANALYZE_NER_TYPE_MODEL_CONFIDENCE`
- **Type**: Float (0.0-1.0)
- **Default**: `0.85`
- **Description**: Minimum confidence threshold for type predictions. Higher values reduce false positives.

### Language Identification

#### `FTM_ANALYZE_LID_MODEL_PATH`
- **Type**: String (path)
- **Default**: `"./models/lid.176.ftz"`
- **Description**: Local path to the language identification (LID) fastText model.

### Model Configuration

#### `FTM_ANALYZE_SPACY_MODELS_*`
- **Type**: Various (nested configuration)
- **Description**: Spacy model configuration for different languages. Use environment variables with pattern `FTM_ANALYZE_SPACY_MODELS_{LANG}` to specify models.
- **Example**: `FTM_ANALYZE_SPACY_MODELS_EN=en_core_web_lg`

#### `FTM_ANALYZE_FLAIR_MODELS_*`
- **Type**: Various (nested configuration)
- **Description**: Flair model configuration for different languages. Use environment variables with pattern `FTM_ANALYZE_FLAIR_MODELS_{LANG}`.

#### `FTM_ANALYZE_BERT_MODEL`
- **Type**: String
- **Default**: `"dslim/bert-base-NER"`
- **Description**: Hugging Face model identifier when using BERT transformer engine.

### Entity Resolution and Refinement

#### `FTM_ANALYZE_RESOLVE_MENTIONS`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Enable resolution of known entity mentions via the `juditha` service. Links entities to known references.

#### `FTM_ANALYZE_REFINE_MENTIONS`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Enable schema classification refinement for mentions via `juditha` fastText model. Improves entity type accuracy.

#### `FTM_ANALYZE_ANNOTATE`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Insert annotations into `indexText` field for resolved mentions. Enables mention-aware search.

#### `FTM_ANALYZE_VALIDATE_NAMES`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Validate NER results against known name tokens via `juditha`. Filters out unlikely entity names.

---

## Configuration Examples

### Minimal Production Setup

```bash
# Required
ALEPH_SECRET_KEY=your-secret-key-here
OPENALEPH_DB_URI=postgresql://user:pass@db:5432/aleph

# Instance details
ALEPH_APP_TITLE=My Investigation Platform
ALEPH_UI_URL=https://aleph.example.com

# Email
ALEPH_MAIL_FROM=noreply@example.com
ALEPH_MAIL_HOST=smtp.example.com
ALEPH_MAIL_USERNAME=smtp-user
ALEPH_MAIL_PASSWORD=smtp-pass

# Admin users
ALEPH_ADMINS=admin@example.com
```

### OAuth/OIDC Setup

```bash
# Enable OAuth
ALEPH_OAUTH=true
ALEPH_OAUTH_HANDLER=oidc
ALEPH_OAUTH_KEY=your-client-id
ALEPH_OAUTH_SECRET=your-client-secret
ALEPH_OAUTH_METADATA_URL=https://idp.example.com/.well-known/openid-configuration
ALEPH_OAUTH_ADMIN_GROUP=aleph-admins

# Disable password login
ALEPH_PASSWORD_LOGIN=false
```

### High-Availability Setup

```bash
# Database connection pooling
ALEPH_SQLALCHEMY_POOL_SIZE=20
ALEPH_SQLALCHEMY_POOL_TIMEOUT=60

# Index replication
ALEPH_INDEX_REPLICAS=2

# Enable monitoring
PROMETHEUS_ENABLED=true
SENTRY_DSN=https://xxx@sentry.io/xxx
SENTRY_ENVIRONMENT=production
```

### Development Setup

```bash
# Minimal for local development
ALEPH_SECRET_KEY=dev-secret-not-for-production
ALEPH_DEBUG=true
ALEPH_SINGLE_USER=true
OPENALEPH_DB_URI=postgresql://aleph:aleph@localhost/aleph
```

---

## See Also

- [Services Architecture](services.md) - Understanding Aleph's service components
- [Docker Deployment](docker.md) - Container-based deployment guide
- [Backup and Restore](backup.md) - Data backup procedures
