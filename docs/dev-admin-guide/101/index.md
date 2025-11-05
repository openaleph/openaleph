# OpenAleph Deployment

## Read this first

OpenAleph is a complex full-stack software intended to store, process and search sensitive material for investigations. Therefore, deploying this software requires sufficient knowledge about infrastructure and service deployments, scaling services for high load and especially security measurements for web-facing services.

While we provide an [example docker-compose.yml setup](../102/docker.md), this is **only an example reference** for how to get started. **NEVER JUST COPY & PASTE THIS AND DEPLOY IT**.

Therefore, we don't provide a step-by-step guide on how to deploy OpenAleph from scratch in our documentation. Someone who deploys this complex and security-sensitive software stack must have sufficient knowledge to do the basic pre-requisite steps. The example docker compose, our [services overview](../102/services.md) and [configuration reference](../102/configuration.md) should be enough for an experienced dev person to run OpenAleph in production.

## Get started

- [Services overview](../102/services.md)
- [Configuration reference](../102/services.md)
- [Minimal docker example](../102/docker.md)
- [Migrating from pre-5 versions](../103/upgrade-3x.md)
- [Reindexing OpenAleph Elasticsearch](../103/reindex.md)

## Get help

Join our discourse community at [darc.social](https://darc.social) for any questions around developing and deploying OpenAleph! We are happy to help.
