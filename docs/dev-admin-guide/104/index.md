# Development Guide

This section covers how to set up a local development environment for contributing to Aleph.

## Overview

Aleph uses a **local-first development** approach:

- **Services** (PostgreSQL, Elasticsearch, Redis, Ingestors, Analyzers) run in Docker containers
- **Backend** (API, App worker) runs locally on your machine
- **Frontend** (React UI) runs locally with hot reload

This approach provides faster iteration, easier debugging, and a simpler setup compared to running everything in containers.

## Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.12+**
- **Node.js 20+** and npm
- **Docker** and Docker Compose
- **Git**

## Quick Start

```bash
# Clone the repository
git clone https://github.com/openaleph/openaleph.git
cd openaleph

# Start services (postgres, elasticsearch, redis, ingest, analyze)
make services

# Install Python dependencies
make dev

# Run database migrations
make upgrade

# In one terminal - run the API
make api

# In another terminal - run the worker
make worker

# In another terminal - run the UI
make ui
```

The application will be available at:

- **UI**: http://localhost:3000
- **API**: http://localhost:5000
