COMPOSE = docker compose
ALEPH_TAG ?= latest

# =============================================================================
# Environment for local development
# =============================================================================
export ALEPH_DEBUG := true
export ALEPH_SECRET_KEY := development
export ALEPH_SINGLE_USER := true
export ALEPH_UI_URL := http://localhost:3000
export ARCHIVE_TYPE := file
export ARCHIVE_PATH := data
export OPENALEPH_ELASTICSEARCH_URI := http://localhost:9200
export OPENALEPH_DB_URI := postgresql://aleph:aleph@localhost:5432/aleph
export PROCRASTINATE_DB_URI := postgresql://aleph:aleph@localhost:5432/aleph
export FTM_FRAGMENTS_URI := postgresql://aleph:aleph@localhost:5432/aleph
export REDIS_URL := redis://localhost:6379
export PROCRASTINATE_APP := aleph.procrastinate.tasks.app
export OPENALEPH_SEARCH_AUTH := 1
export OPENALEPH_SEARCH_AUTH_FIELD := collection_id

# =============================================================================
# Development (local)
# =============================================================================

services:
	$(COMPOSE) up -d postgres elasticsearch redis ingest-file ftm-analyze ftm-translate

stop:
	$(COMPOSE) down --remove-orphans

api: services
	FLASK_APP=aleph.wsgi flask run -h 0.0.0.0 -p 5000 --with-threads --reload --debugger

worker: services
	procrastinate worker -q openaleph,openaleph-management --concurrency 2

ui:
	cd ui && npm start

upgrade: services
	@$(COMPOSE) exec postgres pg_isready --timeout=30
	@$(COMPOSE) exec elasticsearch timeout 30 bash -c "printf 'Waiting for elasticsearch'; until curl --silent --output /dev/null localhost:9200/_cat/health?h=st; do printf '.'; sleep 1; done; printf '\n'"
	aleph upgrade

update: services
	aleph update

shell: services
	aleph shell

tail:
	$(COMPOSE) logs -f

# =============================================================================
# Testing & Linting
# =============================================================================

test: services
	pytest aleph/tests/ $(file)

lint:
	ruff check .

lint-ui:
	cd ui && npm run lint

format:
	black --extend-exclude aleph/migrate aleph/

format-ui:
	cd ui && npm run format

format-check:
	black --check --extend-exclude aleph/migrate aleph/

format-check-ui:
	cd ui && npm run format:check

# =============================================================================
# Build
# =============================================================================

build:
	docker build -t ghcr.io/openaleph/openaleph:$(ALEPH_TAG) .

build-ui:
	docker build -t ghcr.io/openaleph/aleph-ui:$(ALEPH_TAG) ui/

build-all: build build-ui

# =============================================================================
# Development setup
# =============================================================================

install:
	python3 -m pip install --upgrade pip
	python3 -m pip install -q --no-deps -r requirements.txt

dev: install
	python3 -m pip install -q --no-deps -r requirements-dev.txt

dev-ui:
	cd ui && npm install

fixtures:
	aleph crawldir -f fixtures aleph/tests/fixtures/samples

# =============================================================================
# Translations
# =============================================================================

translate: dev
	cd ui && npm run messages
	pybabel extract -F babel.cfg -k lazy_gettext -o aleph/translations/messages.pot aleph
	tx push --source
	tx pull -a -f
	cd ui && npm run translate
	pybabel compile -d aleph/translations -D aleph -f

# =============================================================================
# Utilities
# =============================================================================

clean:
	rm -rf dist build .eggs ui/build
	find . -name '*.egg-info' -exec rm -fr {} +
	find . -name '*.egg' -exec rm -f {} +
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -type d -name __pycache__ -exec rm -r {} \+
	find ui/src -name '*.css' -exec rm -f {} +

migrations:
	FLASK_APP=aleph.wsgi flask db migrate

documentation:
	mkdocs build

.PHONY: services stop api worker ui upgrade update shell tail test lint format build install dev clean
