# PostgreSQL and migration bootstrap

Task 001 provides a local PostgreSQL 16 instance with the `pgvector` extension
available in the server image. No application tables or initial migrations are
created until their owning domain task defines the schema.

## Local services

Start the API and database:

```bash
docker compose up -d --build
```

Check their state:

```bash
docker compose ps
curl --fail http://localhost:8000/health
```

Stop the services without deleting database data:

```bash
docker compose down
```

The Compose defaults are synthetic development-only values, and published
ports bind to `127.0.0.1`. `POSTGRES_DB`, `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_PORT`, `API_PORT`, and `DATABASE_URL` can be
overridden through the environment. Pilot deployments must supply database
credentials through an environment or secret provider instead of using the
development defaults.

## Alembic

`DATABASE_URL` overrides the local URL in `alembic.ini`. Check the migration
environment without connecting to a database:

```bash
alembic upgrade head --sql
```

Future schema-owning tasks create revisions under `migrations/versions` and
must test upgrading from an empty database.
