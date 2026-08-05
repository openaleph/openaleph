#!/bin/sh
# Start a single-user OpenAleph instance using the example Docker stack.

set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
COMPOSE_FILE="$ROOT_DIR/docker-compose.example.yml"
ENV_FILE="$ROOT_DIR/aleph.env"

if ! command -v docker >/dev/null 2>&1; then
  printf '%s\n' 'Docker is required. Install Docker and try again.' >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  printf '%s\n' 'Docker Compose v2 is required. Install it and try again.' >&2
  exit 1
fi

if ! command -v openssl >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1; then
  printf '%s\n' 'openssl and curl are required. Install them and try again.' >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  secret_key=$(openssl rand -hex 32)
  (
    umask 077
    sed \
      -e "s/^ALEPH_SECRET_KEY=.*/ALEPH_SECRET_KEY=$secret_key/" \
      -e 's/^ALEPH_SINGLE_USER=.*/ALEPH_SINGLE_USER=true/' \
      -e 's,^# FTM_FRAGMENTS_URI=postgresql://aleph:aleph@postgres/aleph,FTM_FRAGMENTS_URI=postgresql://aleph:aleph@postgres/aleph,' \
      "$ROOT_DIR/aleph.env.tmpl" >"$ENV_FILE"
  )
  printf '%s\n' 'Created aleph.env with a generated secret key, single-user mode enabled and the default fragments db url.'
else
  printf '%s\n' 'Using existing aleph.env without changes.'
fi

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

printf '%s\n' 'Starting OpenAleph services...'
compose up -d

printf '%s\n' 'Waiting for Elasticsearch to become green...'
attempt=0
until compose exec -T elasticsearch curl -fsS \
  'http://localhost:9200/_cluster/health?wait_for_status=green&timeout=1s' \
  >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 120 ]; then
    printf '%s\n' 'Elasticsearch did not become green within 10 minutes.' >&2
    printf '%s\n' 'Inspect the service with: docker compose -f docker-compose.example.yml logs elasticsearch' >&2
    exit 1
  fi
  sleep 5
done

printf '%s\n' 'Initializing the database and search index...'
compose run --rm worker aleph upgrade

printf '%s\n' 'Waiting for the web interface...'
attempt=0
until curl -fsS http://localhost:8080/ >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 60 ]; then
    printf '%s\n' 'The web interface did not become available within 5 minutes.' >&2
    printf '%s\n' 'Inspect services with: docker compose -f docker-compose.example.yml logs' >&2
    exit 1
  fi
  sleep 5
done

printf '%s\n' 'OpenAleph is running at http://localhost:8080/'
