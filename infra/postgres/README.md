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

## Domain persistence

Task 006 stores normalized internal copies of the nine canonical domain entity
types. `DomainRepository` provides insert-by-entity and get-by-canonical-UUID
only. It does not commit transactions, upsert source records, delete data, or
write back to ERP, MES, or PLM.

Apply the domain schema with an application database URL:

```bash
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE \
  alembic upgrade head
```

Generate offline deployment SQL without connecting:

```bash
alembic upgrade head --sql
```

PostgreSQL integration tests use only `TEST_DATABASE_URL`. The database name
must end in `_test`; the tests refuse any other name before connecting. Start
an isolated local test database with:

```bash
COMPOSE_PROJECT_NAME=shipyard_ai_task006 \
POSTGRES_DB=shipyard_ai_test \
POSTGRES_PORT=55432 \
docker compose up -d postgres
```

Run the repository tests with:

```bash
TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
  python -m pytest tests/integration/test_domain_repository.py -v
```

If `TEST_DATABASE_URL` is absent, this PostgreSQL-specific module skips
locally. CI always provisions PostgreSQL and supplies the variable, so the
repository and migration tests are mandatory in the quality gate.
