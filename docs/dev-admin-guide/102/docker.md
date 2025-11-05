# Example docker-compose.yml

[Read this first](../101/index.md)

We provide a reference `docker-compose.yml` as a starting point. The [online version in the OpenAleph repository contains the current image tags](https://github.com/openaleph/openaleph/blob/main/docker-compose.yml)

This is a minimal working example:

```yaml
services:
  postgres:
    image: postgres:latest
    volumes:
      - postgres-data:/var/lib/postgresql/data
    environment:
      POSTGRES_USER: aleph
      POSTGRES_PASSWORD: aleph
      POSTGRES_DATABASE: aleph

  elasticsearch:
    image: ghcr.io/openaleph/elasticsearch:latest
    hostname: elasticsearch
    environment:
      - discovery.type=single-node
    volumes:
      - elasticsearch-data:/usr/share/elasticsearch/data

  redis:
    image: redis:alpine
    command: [ "redis-server", "--save", "3600", "10" ]

  ingest:
    image: ghcr.io/openaleph/ingest-file:latest
    command: procrastinate worker -q ingest
    tmpfs:
      - /tmp:mode=777
    volumes:
      - archive-data:/data
    depends_on:
      - postgres
      - redis
    restart: on-failure
    env_file:
      - aleph.env

  analyze:
    image: ghcr.io/openaleph/ftm-analyze:latest
    command: procrastinate worker -q analyze
    tmpfs:
      - /tmp:mode=777
    depends_on:
      - postgres
      - redis
    restart: on-failure
    env_file:
      - aleph.env

  worker:
    image: ghcr.io/openaleph/openaleph:latest
    command: procrastinate worker -q openaleph
    restart: on-failure
    depends_on:
      - postgres
      - elasticsearch
      - redis
      - ingest
    tmpfs:
      - /tmp
    volumes:
      - archive-data:/data
    env_file:
      - aleph.env

  api:
    image: ghcr.io/openaleph/openaleph:latest
    expose:
      - 8000
    depends_on:
      - postgres
      - elasticsearch
      - redis
      - worker
      - ingest
    tmpfs:
      - /tmp
    volumes:
      - archive-data:/data
    env_file:
      - aleph.env

  ui:
    image: ghcr.io/openaleph/aleph-ui:latest
    depends_on:
      - api
    ports:
      - "8080:8080"

volumes:
  archive-data: {}
  postgres-data: {}
  elasticsearch-data: {}
```

Minimum environment configuration (`aleph.env`), all others have reasonable defaults. Archive, Database and Elasticsearch connections are pre-defined in the docker containers to work with the above example compose file.

```bash
ALEPH_SECRET_KEY=random-secret-string
ALEPH_SINGLE_USER=true  # no user management at all for quick local set up
# best practice to set db uris explicitly:
OPENALEPH_DB_URI=postgresql://aleph:aleph@postgres
FTM_FRAGMENTS_URI=postgresql://aleph:aleph@postgres
PROCRASTINATE_DB_URI=postgresql://aleph:aleph@postgres
```

## Initial setup

On a fresh database and index, starting up the containers will throw errors about database migrations and elasticsearch indices not present. To initialize (or upgrade), run within an app container (api or worker): `aleph upgrade`.

Check the logs of the elasticsearch container to wait until it is properly up (health status changed to GREEN). Then run:

```bash
docker compose run --rm worker aleph upgrade
```

OpenAleph is then reachable at [localhost:8080](http://localhost:8080)
