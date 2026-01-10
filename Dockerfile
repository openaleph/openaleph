# =============================================================================
# Stage 1: Build dependencies
# =============================================================================
# This stage installs build tools and compiles Python dependencies.
# Heavy packages like pyicu require compilation.
FROM python:3.13-slim AS builder

ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies
RUN apt-get -qq -y update \
    && apt-get -qq --no-install-recommends -y install \
        build-essential \
        pkg-config \
        libicu-dev \
        libpq-dev \
        git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment for clean copying to runtime
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip
RUN pip install --no-cache-dir -U pip setuptools wheel

# Install pyicu separately (requires compilation, not in requirements.txt)
RUN pip install --no-cache-dir --no-binary=:pyicu: pyicu

# Copy and install requirements (--no-deps since requirements.txt is fully frozen)
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --no-deps -r /tmp/requirements.txt

# Install the aleph package itself
COPY . /aleph-src
RUN pip install --no-cache-dir --no-deps /aleph-src

# Clean up unnecessary files to reduce image size
RUN find /opt/venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true \
    && find /opt/venv -type f -name "*.pyc" -delete \
    && find /opt/venv -type f -name "*.pyo" -delete \
    && find /opt/venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true \
    && find /opt/venv -type d -name "test" -exec rm -rf {} + 2>/dev/null || true \
    && rm -rf /opt/venv/share/doc \
    && rm -rf /opt/venv/share/man

# =============================================================================
# Stage 2: Download models
# =============================================================================
# Separate stage for downloading large model files.
# This allows model updates without rebuilding dependencies.
FROM python:3.13-slim AS models

RUN apt-get -qq -y update \
    && apt-get -qq --no-install-recommends -y install curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV ALEPH_WORD_FREQUENCY_URI=https://public.data.occrp.org/develop/models/word-frequencies/word_frequencies-v0.4.1.zip
ENV ALEPH_FTM_COMPARE_MODEL_URI=https://public.data.occrp.org/develop/models/xref/glm_bernoulli_2e_wf-v0.4.1.pkl

RUN mkdir -p /opt/ftm-compare/word-frequencies/ \
    && curl -L -o "/opt/ftm-compare/word-frequencies/word-frequencies.zip" "$ALEPH_WORD_FREQUENCY_URI" \
    && python3 -m zipfile --extract /opt/ftm-compare/word-frequencies/word-frequencies.zip /opt/ftm-compare/word-frequencies/ \
    && rm /opt/ftm-compare/word-frequencies/word-frequencies.zip \
    && curl -L -o "/opt/ftm-compare/model.pkl" "$ALEPH_FTM_COMPARE_MODEL_URI"

# =============================================================================
# Stage 3: Runtime
# =============================================================================
# Minimal runtime image without build tools.
FROM python:3.13-slim AS runtime

LABEL org.opencontainers.image.source="https://github.com/openaleph/openaleph"
LABEL org.opencontainers.image.description="Aleph - Follow The Money"

ENV DEBIAN_FRONTEND=noninteractive \
    # Python optimizations
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install only runtime dependencies (no build-essential)
RUN apt-get -qq -y update \
    && apt-get -qq --no-install-recommends -y install \
        locales \
        ca-certificates \
        postgresql-client \
        libpq5 \
        libicu76 \
        curl \
        jq \
    && apt-get -qq -y autoremove \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* \
    && localedef -i en_US -c -f UTF-8 -A /usr/share/locale/locale.alias en_US.UTF-8

ENV LANG='en_US.UTF-8'

# Create non-root user
RUN groupadd -g 1000 -r app \
    && useradd -m -u 1000 -s /bin/false -g app app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy model files from models stage
COPY --from=models /opt/ftm-compare /opt/ftm-compare

# Copy application code
COPY --chown=app:app aleph /aleph/aleph
COPY --chown=app:app gunicorn.conf.py /aleph/gunicorn.conf.py
COPY --chown=app:app pyproject.toml /aleph/pyproject.toml
COPY --chown=app:app docker-entrypoint.sh /docker-entrypoint.sh
COPY --chown=app:app docker-entrypoint.d /docker-entrypoint.d/

WORKDIR /aleph
ENV PYTHONPATH=/aleph

# Configure runtime defaults
ENV OPENALEPH_ELASTICSEARCH_URI=http://elasticsearch:9200/ \
    OPENALEPH_DB_URI=postgresql://aleph:aleph@postgres/aleph \
    PROCRASTINATE_DB_URI=postgresql://aleph:aleph@postgres/aleph \
    FTM_FRAGMENTS_URI=postgresql://aleph:aleph@postgres/aleph \
    REDIS_URL=redis://redis:6379/0 \
    ARCHIVE_TYPE=file \
    ARCHIVE_PATH=/data \
    FTM_COMPARE_FREQUENCIES_DIR=/opt/ftm-compare/word-frequencies/ \
    FTM_COMPARE_MODEL=/opt/ftm-compare/model.pkl \
    PROCRASTINATE_APP=aleph.procrastinate.tasks.app \
    OPENALEPH_SEARCH_AUTH=1 \
    OPENALEPH_SEARCH_AUTH_FIELD=collection_id \
    OPENALEPH_SEARCH_INDEX_NAMESPACE_IDS=1

RUN mkdir -p /run/prometheus && chown app:app /run/prometheus \
    && chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["gunicorn", "--config", "/aleph/gunicorn.conf.py", "--workers", "6", "--log-level", "info", "--log-file", "-"]
