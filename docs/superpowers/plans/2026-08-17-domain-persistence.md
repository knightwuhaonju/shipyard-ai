# Task 006 Domain Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist all nine Task 005 domain entities in PostgreSQL with exact domain round-trips, relational constraints, a safe minimal repository, and an Alembic migration that upgrades an empty database.

**Architecture:** Keep `packages/domain` framework-independent. Define separate SQLAlchemy 2.x ORM models under `infra/postgres`, convert explicitly at a single `DomainRepository` boundary, and mirror feasible domain invariants with PostgreSQL constraints. Exercise migrations and repositories against a dedicated `_test` PostgreSQL database supplied locally through `TEST_DATABASE_URL` and unconditionally by CI.

**Tech Stack:** Python 3.12.13, SQLAlchemy 2.x, Alembic, psycopg 3, PostgreSQL 16 with pgvector image, pytest, Ruff, mypy, Docker Compose, GitHub Actions.

## Global Constraints

- Implement Task 006 only; do not add `EntityAlias` or any Task 007 behavior.
- `packages/domain` remains unchanged and imports only the Python standard library and `packages.domain` modules.
- Canonical entity IDs are PostgreSQL UUID primary keys and remain distinct from source-system IDs.
- Every entity table contains non-blank `source_system`, non-blank `source_id`, timezone-aware `source_updated_at`, and a per-table unique `(source_system, source_id)` pair.
- ORM models are separate from the frozen, slotted domain dataclasses.
- The public repository surface is exactly `insert(entity) -> None` and `get(entity_type, entity_id) -> entity | None` for the nine Task 005 types.
- The repository does not commit, retry, update, delete, merge, or upsert.
- The caller owns the SQLAlchemy Session and outer transaction.
- PostgreSQL foreign keys use default `NO ACTION`; no cascade deletes or graph database are introduced.
- Quantity uses unrestricted PostgreSQL `NUMERIC` and must be finite and greater than zero.
- Progress uses unrestricted PostgreSQL `NUMERIC` and must be finite and within inclusive `0..1`.
- Purchase-order source dates have no relative ordering constraint.
- Integration tests read only `TEST_DATABASE_URL`, never `DATABASE_URL`, and reject database names that do not end in `_test` before connecting.
- Missing `TEST_DATABASE_URL` skips the PostgreSQL integration module locally; GitHub Actions always supplies it.
- Tests use deterministic synthetic shipyard data and make no network or external model calls.
- Migration revisions live under `infra/postgres/migrations/versions/`, matching the existing `alembic.ini` script location.
- Validation and persistence errors do not include rejected business values or database credentials.

---

### Task 1: SQLAlchemy Domain Metadata

**Files:**
- Create: `infra/__init__.py`
- Create: `infra/postgres/__init__.py`
- Create: `infra/postgres/models.py`
- Create: `tests/integration/test_domain_repository.py`

**Interfaces:**
- Consumes: the nine immutable classes and `PositiveQuantity`/`Progress` contracts from `packages.domain`.
- Produces: `Base.metadata` and ORM classes `ShipModel`, `ShipSystemModel`, `DrawingModel`, `EquipmentModel`, `MaterialModel`, `BOMItemModel`, `SupplierModel`, `PurchaseOrderModel`, and `ProjectTaskModel`.

- [ ] **Step 1: Create package markers and the first failing metadata tests**

Create empty `infra/__init__.py` and `infra/postgres/__init__.py` files.

Create `tests/integration/test_domain_repository.py` with:

```python
from __future__ import annotations

from sqlalchemy import CheckConstraint, DateTime, UniqueConstraint


DOMAIN_TABLES = {
    "bom_items",
    "drawings",
    "equipment",
    "materials",
    "project_tasks",
    "purchase_orders",
    "ship_systems",
    "ships",
    "suppliers",
}


def test_domain_metadata_declares_all_entity_tables_and_source_fields() -> None:
    from infra.postgres.models import Base

    assert set(Base.metadata.tables) == DOMAIN_TABLES
    for table in Base.metadata.tables.values():
        assert {"id", "source_system", "source_id", "source_updated_at"} <= {
            column.name for column in table.columns
        }
        assert table.c.id.primary_key
        assert not table.c.source_system.nullable
        assert not table.c.source_id.nullable
        assert not table.c.source_updated_at.nullable
        assert isinstance(table.c.source_updated_at.type, DateTime)
        assert table.c.source_updated_at.type.timezone is True
        assert any(
            isinstance(constraint, UniqueConstraint)
            and {column.name for column in constraint.columns}
            == {"source_system", "source_id"}
            for constraint in table.constraints
        )


def test_domain_metadata_matches_documented_foreign_keys() -> None:
    from infra.postgres.models import Base

    expected = {
        "ship_systems": {"ship_id": "ships.id"},
        "drawings": {"ship_id": "ships.id", "system_id": "ship_systems.id"},
        "equipment": {
            "ship_id": "ships.id",
            "system_id": "ship_systems.id",
            "drawing_id": "drawings.id",
        },
        "bom_items": {
            "drawing_id": "drawings.id",
            "equipment_id": "equipment.id",
            "material_id": "materials.id",
        },
        "purchase_orders": {
            "ship_id": "ships.id",
            "material_id": "materials.id",
            "equipment_id": "equipment.id",
            "supplier_id": "suppliers.id",
        },
        "project_tasks": {"ship_id": "ships.id"},
    }

    for table_name, expected_targets in expected.items():
        table = Base.metadata.tables[table_name]
        actual_targets = {
            column.name: next(iter(column.foreign_keys)).target_fullname
            for column in table.columns
            if column.foreign_keys
        }
        assert actual_targets == expected_targets


def test_domain_metadata_names_every_database_check() -> None:
    from infra.postgres.models import Base

    required_checks = {
        "bom_items": {"ck_bom_items_target", "ck_bom_items_quantity"},
        "project_tasks": {
            "ck_project_tasks_planned_dates",
            "ck_project_tasks_actual_dates",
            "ck_project_tasks_planned_progress",
            "ck_project_tasks_actual_progress",
        },
        "purchase_orders": {
            "ck_purchase_orders_target",
            "ck_purchase_orders_quantity",
        },
    }

    for table_name, names in required_checks.items():
        table = Base.metadata.tables[table_name]
        actual = {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert names <= actual
```

- [ ] **Step 2: Run the metadata tests and confirm RED**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_domain_repository.py -v
```

Expected: collection succeeds and all three tests fail with
`ModuleNotFoundError: No module named 'infra.postgres.models'`.

- [ ] **Step 3: Implement the exact ORM metadata**

Create `infra/postgres/models.py`:

```python
"""SQLAlchemy persistence models for the canonical shipyard domain."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.schema import Constraint


class Base(DeclarativeBase):
    """Declarative metadata root for PostgreSQL infrastructure."""


def _source_constraints(table: str) -> tuple[Constraint, ...]:
    return (
        UniqueConstraint(
            "source_system",
            "source_id",
            name=f"uq_{table}_source_identity",
        ),
        CheckConstraint(
            "btrim(source_system) <> ''",
            name=f"ck_{table}_source_system_non_blank",
        ),
        CheckConstraint(
            "btrim(source_id) <> ''",
            name=f"ck_{table}_source_id_non_blank",
        ),
    )


class _SourcedModel:
    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ShipModel(_SourcedModel, Base):
    __tablename__ = "ships"
    __table_args__ = (
        *_source_constraints(__tablename__),
        UniqueConstraint("ship_code", name="uq_ships_ship_code"),
        CheckConstraint("btrim(ship_code) <> ''", name="ck_ships_ship_code"),
        CheckConstraint(
            "name IS NULL OR btrim(name) <> ''", name="ck_ships_name"
        ),
        CheckConstraint(
            "customer_name IS NULL OR btrim(customer_name) <> ''",
            name="ck_ships_customer_name",
        ),
        CheckConstraint(
            "vessel_type IS NULL OR btrim(vessel_type) <> ''",
            name="ck_ships_vessel_type",
        ),
    )

    ship_code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    customer_name: Mapped[str | None] = mapped_column(Text)
    vessel_type: Mapped[str | None] = mapped_column(Text)
    planned_delivery_date: Mapped[date | None] = mapped_column(Date)


class ShipSystemModel(_SourcedModel, Base):
    __tablename__ = "ship_systems"
    __table_args__ = (
        *_source_constraints(__tablename__),
        CheckConstraint(
            "btrim(system_code) <> ''", name="ck_ship_systems_system_code"
        ),
        CheckConstraint("btrim(name) <> ''", name="ck_ship_systems_name"),
    )

    ship_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ships.id", name="fk_ship_systems_ship_id"),
        nullable=False,
        index=True,
    )
    system_code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class DrawingModel(_SourcedModel, Base):
    __tablename__ = "drawings"
    __table_args__ = (
        *_source_constraints(__tablename__),
        CheckConstraint(
            "btrim(drawing_no) <> ''", name="ck_drawings_drawing_no"
        ),
        CheckConstraint("btrim(title) <> ''", name="ck_drawings_title"),
        CheckConstraint("btrim(revision) <> ''", name="ck_drawings_revision"),
        CheckConstraint(
            "status IS NULL OR btrim(status) <> ''", name="ck_drawings_status"
        ),
    )

    ship_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ships.id", name="fk_drawings_ship_id"),
        nullable=False,
        index=True,
    )
    system_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ship_systems.id", name="fk_drawings_system_id"),
        index=True,
    )
    drawing_no: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str | None] = mapped_column(Text)


class EquipmentModel(_SourcedModel, Base):
    __tablename__ = "equipment"
    __table_args__ = (
        *_source_constraints(__tablename__),
        CheckConstraint(
            "btrim(equipment_code) <> ''", name="ck_equipment_equipment_code"
        ),
        CheckConstraint(
            "manufacturer IS NULL OR btrim(manufacturer) <> ''",
            name="ck_equipment_manufacturer",
        ),
        CheckConstraint(
            "model IS NULL OR btrim(model) <> ''", name="ck_equipment_model"
        ),
    )

    ship_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ships.id", name="fk_equipment_ship_id"),
        nullable=False,
        index=True,
    )
    system_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ship_systems.id", name="fk_equipment_system_id"),
        index=True,
    )
    drawing_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("drawings.id", name="fk_equipment_drawing_id"),
        index=True,
    )
    equipment_code: Mapped[str] = mapped_column(Text, nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)


class MaterialModel(_SourcedModel, Base):
    __tablename__ = "materials"
    __table_args__ = (
        *_source_constraints(__tablename__),
        CheckConstraint(
            "btrim(material_code) <> ''", name="ck_materials_material_code"
        ),
        CheckConstraint(
            "btrim(description) <> ''", name="ck_materials_description"
        ),
        CheckConstraint(
            "specification IS NULL OR btrim(specification) <> ''",
            name="ck_materials_specification",
        ),
        CheckConstraint(
            "unit IS NULL OR btrim(unit) <> ''", name="ck_materials_unit"
        ),
    )

    material_code: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    specification: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(Text)


class BOMItemModel(_SourcedModel, Base):
    __tablename__ = "bom_items"
    __table_args__ = (
        *_source_constraints(__tablename__),
        CheckConstraint(
            "drawing_id IS NOT NULL OR equipment_id IS NOT NULL",
            name="ck_bom_items_target",
        ),
        CheckConstraint(
            "quantity > 0 AND quantity < 'Infinity'::numeric",
            name="ck_bom_items_quantity",
        ),
    )

    drawing_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("drawings.id", name="fk_bom_items_drawing_id"),
        index=True,
    )
    equipment_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("equipment.id", name="fk_bom_items_equipment_id"),
        index=True,
    )
    material_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("materials.id", name="fk_bom_items_material_id"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)


class SupplierModel(_SourcedModel, Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        *_source_constraints(__tablename__),
        CheckConstraint(
            "btrim(supplier_code) <> ''", name="ck_suppliers_supplier_code"
        ),
        CheckConstraint(
            "btrim(canonical_name) <> ''", name="ck_suppliers_canonical_name"
        ),
    )

    supplier_code: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)


class PurchaseOrderModel(_SourcedModel, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        *_source_constraints(__tablename__),
        CheckConstraint(
            "material_id IS NOT NULL OR equipment_id IS NOT NULL",
            name="ck_purchase_orders_target",
        ),
        CheckConstraint(
            "quantity IS NULL OR "
            "(quantity > 0 AND quantity < 'Infinity'::numeric)",
            name="ck_purchase_orders_quantity",
        ),
        CheckConstraint(
            "btrim(po_number) <> ''", name="ck_purchase_orders_po_number"
        ),
        CheckConstraint(
            "btrim(status) <> ''", name="ck_purchase_orders_status"
        ),
        CheckConstraint(
            "criticality IS NULL OR btrim(criticality) <> ''",
            name="ck_purchase_orders_criticality",
        ),
    )

    ship_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ships.id", name="fk_purchase_orders_ship_id"),
        nullable=False,
        index=True,
    )
    material_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("materials.id", name="fk_purchase_orders_material_id"),
        index=True,
    )
    equipment_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("equipment.id", name="fk_purchase_orders_equipment_id"),
        index=True,
    )
    supplier_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("suppliers.id", name="fk_purchase_orders_supplier_id"),
        nullable=False,
        index=True,
    )
    po_number: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    required_date: Mapped[date | None] = mapped_column(Date)
    promised_date: Mapped[date | None] = mapped_column(Date)
    actual_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    criticality: Mapped[str | None] = mapped_column(Text)


class ProjectTaskModel(_SourcedModel, Base):
    __tablename__ = "project_tasks"
    __table_args__ = (
        *_source_constraints(__tablename__),
        CheckConstraint(
            "btrim(task_code) <> ''", name="ck_project_tasks_task_code"
        ),
        CheckConstraint("btrim(name) <> ''", name="ck_project_tasks_name"),
        CheckConstraint(
            "planned_start IS NULL OR planned_end IS NULL "
            "OR planned_start <= planned_end",
            name="ck_project_tasks_planned_dates",
        ),
        CheckConstraint(
            "actual_start IS NULL OR actual_end IS NULL "
            "OR actual_start <= actual_end",
            name="ck_project_tasks_actual_dates",
        ),
        CheckConstraint(
            "planned_progress IS NULL OR "
            "(planned_progress >= 0 AND planned_progress <= 1)",
            name="ck_project_tasks_planned_progress",
        ),
        CheckConstraint(
            "actual_progress IS NULL OR "
            "(actual_progress >= 0 AND actual_progress <= 1)",
            name="ck_project_tasks_actual_progress",
        ),
    )

    ship_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ships.id", name="fk_project_tasks_ship_id"),
        nullable=False,
        index=True,
    )
    task_code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    planned_start: Mapped[date | None] = mapped_column(Date)
    planned_end: Mapped[date | None] = mapped_column(Date)
    actual_start: Mapped[date | None] = mapped_column(Date)
    actual_end: Mapped[date | None] = mapped_column(Date)
    planned_progress: Mapped[Decimal | None] = mapped_column(Numeric)
    actual_progress: Mapped[Decimal | None] = mapped_column(Numeric)
    critical_path: Mapped[bool | None] = mapped_column(Boolean)
```

- [ ] **Step 4: Run focused tests and static checks**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_domain_repository.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  infra tests/integration/test_domain_repository.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  infra tests/integration/test_domain_repository.py
```

Expected: three tests pass; Ruff and mypy pass.

- [ ] **Step 5: Commit the metadata slice**

```bash
git add infra/__init__.py infra/postgres/__init__.py \
  infra/postgres/models.py tests/integration/test_domain_repository.py
git commit -m "feat: add domain persistence metadata"
```

---

### Task 2: Empty-Database Alembic Upgrade and CI PostgreSQL

**Files:**
- Modify: `infra/postgres/migrations/env.py`
- Create: `infra/postgres/migrations/versions/20260817_0001_create_domain_tables.py`
- Modify: `tests/integration/test_domain_repository.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `infra.postgres.models.Base.metadata` from Task 1.
- Produces: Alembic revision `20260817_0001`, test helpers `_validated_test_database_url`, `_alembic_config`, and a CI-provided `TEST_DATABASE_URL`.

- [ ] **Step 1: Add safe database URL and empty-upgrade tests before the migration exists**

Extend the imports in `tests/integration/test_domain_repository.py` to:

```python
from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.engine import URL, make_url
```

Add these constants and helpers below `DOMAIN_TABLES`:

```python
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _validated_test_database_url(raw_url: str) -> URL:
    url = make_url(raw_url)
    if url.database is None or not url.database.endswith("_test"):
        raise ValueError("TEST_DATABASE_URL must name a database ending in _test")
    return url


def _configured_test_database_url() -> URL:
    raw_url = os.getenv("TEST_DATABASE_URL")
    if raw_url is None:
        pytest.skip("TEST_DATABASE_URL is not configured")
    try:
        return _validated_test_database_url(raw_url)
    except ValueError as exc:
        pytest.fail(str(exc), pytrace=False)


def _alembic_config(url: URL) -> Config:
    config = Config(str(REPOSITORY_ROOT / "alembic.ini"))
    rendered_url = url.render_as_string(hide_password=False).replace("%", "%%")
    config.set_main_option("sqlalchemy.url", rendered_url)
    return config
```

Add the tests:

```python
def test_test_database_url_rejects_non_test_database_without_leaking_secret() -> None:
    secret = "do-not-print"
    raw_url = f"postgresql+psycopg://shipyard:{secret}@localhost/shipyard_ai"

    with pytest.raises(ValueError) as captured:
        _validated_test_database_url(raw_url)

    assert str(captured.value) == (
        "TEST_DATABASE_URL must name a database ending in _test"
    )
    assert secret not in str(captured.value)


def test_migration_upgrades_an_empty_postgresql_database() -> None:
    url = _configured_test_database_url()
    config = _alembic_config(url)
    engine = create_engine(url)
    try:
        command.downgrade(config, "base")
        assert DOMAIN_TABLES.isdisjoint(inspect(engine).get_table_names())

        command.upgrade(config, "head")

        table_names = set(inspect(engine).get_table_names())
        assert DOMAIN_TABLES <= table_names
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "20260817_0001"
    finally:
        engine.dispose()
        command.downgrade(config, "base")
```

- [ ] **Step 2: Start an isolated local PostgreSQL test database**

Run from the Task 006 worktree:

```bash
COMPOSE_PROJECT_NAME=shipyard_ai_task006 \
POSTGRES_DB=shipyard_ai_test \
POSTGRES_PORT=55432 \
docker compose up -d postgres
```

Use this exact test URL for all local PostgreSQL commands in the plan:

```text
postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test
```

The distinct Compose project name creates an isolated synthetic volume rather
than reusing the normal development database volume.

- [ ] **Step 3: Run the migration test and confirm RED**

Run:

```bash
TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_domain_repository.py::test_migration_upgrades_an_empty_postgresql_database \
  -v
```

Expected: FAIL because Alembic head has no Task 006 revision and none of the
nine domain tables exists after `upgrade head`.

- [ ] **Step 4: Connect Alembic to Task 1 metadata**

In `infra/postgres/migrations/env.py`, add:

```python
from infra.postgres.models import Base
```

Replace:

```python
target_metadata = None
```

with:

```python
target_metadata = Base.metadata
```

- [ ] **Step 5: Generate the exact first revision from the approved metadata**

Run:

```bash
DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m alembic revision \
  --autogenerate \
  --rev-id 20260817_0001 \
  -m "create domain tables"
```

This creates
`infra/postgres/migrations/versions/20260817_0001_create_domain_tables.py`.
Review the generated revision and require all of the following exact structural
properties before continuing:

```python
revision: str = "20260817_0001"
down_revision: str | Sequence[str] | None = None
```

- `upgrade()` contains nine explicit `op.create_table` calls for the
  `DOMAIN_TABLES` names and explicit indexes for every foreign-key column.
- Every source unique/check constraint and every named Task 1 check appears in
  the generated table operations.
- `downgrade()` drops the nine tables in reverse foreign-key dependency order.
- Neither function calls `Base.metadata.create_all`, `drop_all`, or contains
  `pass`.

If Alembic emits unnamed indexes, give them the SQLAlchemy-generated names
`ix_<table>_<column>` so the migration and metadata agree.

- [ ] **Step 6: Add mandatory PostgreSQL to CI**

Modify `.github/workflows/ci.yml` so the `quality` job contains this service
immediately after `runs-on` and this environment block before `steps`:

```yaml
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_DB: shipyard_ai_test
          POSTGRES_PASSWORD: shipyard_test
          POSTGRES_USER: shipyard_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U shipyard_test -d shipyard_ai_test"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10

    env:
      TEST_DATABASE_URL: >-
        postgresql+psycopg://shipyard_test:shipyard_test@127.0.0.1:5432/shipyard_ai_test
```

Keep the existing pinned action SHAs, permissions, timeout, and quality-gate
steps unchanged.

- [ ] **Step 7: Run migration GREEN, offline SQL, and static checks**

Run:

```bash
TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_domain_repository.py -v
DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m alembic upgrade head --sql
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  infra .github tests/integration/test_domain_repository.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  infra tests/integration/test_domain_repository.py
```

Expected: five tests pass, offline SQL contains all nine `CREATE TABLE`
statements, Ruff passes, and mypy passes.

- [ ] **Step 8: Commit the migration slice**

```bash
git add .github/workflows/ci.yml infra/postgres/migrations/env.py \
  infra/postgres/migrations/versions/20260817_0001_create_domain_tables.py \
  tests/integration/test_domain_repository.py
git commit -m "feat: add domain schema migration"
```

---

### Task 3: Typed Domain Repository Round-Trip

**Files:**
- Create: `infra/postgres/repositories.py`
- Modify: `infra/postgres/__init__.py`
- Modify: `tests/integration/test_domain_repository.py`

**Interfaces:**
- Consumes: Task 1 ORM classes, a caller-owned `sqlalchemy.orm.Session`, and the nine Task 005 entities.
- Produces: `UnsupportedDomainEntityError` and `DomainRepository.insert`/`DomainRepository.get`; safe integrity translation is added in Task 4 after its RED test.

- [ ] **Step 1: Add the failing synthetic graph round-trip tests**

Add these imports to `tests/integration/test_domain_repository.py`:

```python
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Iterator, TypedDict
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from packages.domain import (
    BOMItem,
    Drawing,
    Equipment,
    Material,
    PositiveQuantity,
    Progress,
    ProjectTask,
    PurchaseOrder,
    Ship,
    ShipSystem,
    Supplier,
)
```

Add these fixtures and synthetic data helpers:

```python
class _SourceFields(TypedDict):
    id: UUID
    source_system: str
    source_id: str
    source_updated_at: datetime


SOURCE_UPDATED_AT = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)
SHIP_ID = UUID("10000000-0000-0000-0000-000000000001")
SYSTEM_ID = UUID("10000000-0000-0000-0000-000000000002")
DRAWING_ID = UUID("10000000-0000-0000-0000-000000000003")
EQUIPMENT_ID = UUID("10000000-0000-0000-0000-000000000004")
MATERIAL_ID = UUID("10000000-0000-0000-0000-000000000005")
SUPPLIER_ID = UUID("10000000-0000-0000-0000-000000000006")
BOM_ITEM_ID = UUID("10000000-0000-0000-0000-000000000007")
PURCHASE_ORDER_ID = UUID("10000000-0000-0000-0000-000000000008")
PROJECT_TASK_ID = UUID("10000000-0000-0000-0000-000000000009")


def _source_fields(entity_id: UUID, source_id: str) -> _SourceFields:
    return {
        "id": entity_id,
        "source_system": "synthetic-source",
        "source_id": source_id,
        "source_updated_at": SOURCE_UPDATED_AT,
    }


def _synthetic_domain_graph() -> tuple[
    Ship,
    ShipSystem,
    Drawing,
    Equipment,
    Material,
    Supplier,
    BOMItem,
    PurchaseOrder,
    ProjectTask,
]:
    ship = Ship(
        **_source_fields(SHIP_ID, "ship-001"),
        ship_code="SHIP-001",
        name="Synthetic Vessel",
        customer_name="Synthetic Customer",
        vessel_type="Research Vessel",
        planned_delivery_date=date(2027, 6, 1),
    )
    system = ShipSystem(
        **_source_fields(SYSTEM_ID, "system-001"),
        ship_id=ship.id,
        system_code="SYS-BALLAST",
        name="Ballast System",
    )
    drawing = Drawing(
        **_source_fields(DRAWING_ID, "drawing-001"),
        ship_id=ship.id,
        system_id=system.id,
        drawing_no="DWG-001",
        title="Synthetic Ballast Arrangement",
        revision="A",
        status="RELEASED",
    )
    equipment = Equipment(
        **_source_fields(EQUIPMENT_ID, "equipment-001"),
        ship_id=ship.id,
        system_id=system.id,
        drawing_id=drawing.id,
        equipment_code="EQ-PUMP-001",
        manufacturer="Synthetic Manufacturer",
        model="P-100",
    )
    material = Material(
        **_source_fields(MATERIAL_ID, "material-001"),
        material_code="MAT-001",
        description="Synthetic pipe section",
        specification="DN100",
        unit="m",
    )
    supplier = Supplier(
        **_source_fields(SUPPLIER_ID, "supplier-001"),
        supplier_code="SUP-001",
        canonical_name="Synthetic Supplier",
    )
    bom_item = BOMItem(
        **_source_fields(BOM_ITEM_ID, "bom-001"),
        drawing_id=drawing.id,
        equipment_id=equipment.id,
        material_id=material.id,
        quantity=PositiveQuantity(Decimal("12.5000")),
    )
    purchase_order = PurchaseOrder(
        **_source_fields(PURCHASE_ORDER_ID, "po-001"),
        ship_id=ship.id,
        material_id=material.id,
        equipment_id=equipment.id,
        supplier_id=supplier.id,
        po_number="PO-001",
        quantity=PositiveQuantity(Decimal("20.125000")),
        required_date=date(2027, 3, 1),
        promised_date=date(2027, 2, 15),
        actual_date=date(2027, 1, 20),
        status="DELIVERED",
        criticality="HIGH",
    )
    project_task = ProjectTask(
        **_source_fields(PROJECT_TASK_ID, "task-001"),
        ship_id=ship.id,
        task_code="TASK-001",
        name="Synthetic installation",
        planned_start=date(2027, 1, 1),
        planned_end=date(2027, 1, 31),
        actual_start=date(2027, 1, 2),
        actual_end=date(2027, 2, 2),
        planned_progress=Progress(Decimal("0.750000")),
        actual_progress=Progress(Decimal("0.625000")),
        critical_path=True,
    )
    return (
        ship,
        system,
        drawing,
        equipment,
        material,
        supplier,
        bom_item,
        purchase_order,
        project_task,
    )


@pytest.fixture()
def migrated_engine() -> Iterator[Engine]:
    url = _configured_test_database_url()
    config = _alembic_config(url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(config, "base")


@pytest.fixture()
def migrated_session(migrated_engine: Engine) -> Iterator[Session]:
    with Session(migrated_engine) as session:
        yield session
```

Add the first repository tests:

```python
def test_repository_round_trips_complete_synthetic_domain_graph(
    migrated_session: Session,
) -> None:
    from infra.postgres.repositories import DomainRepository

    repository = DomainRepository(migrated_session)
    entities = _synthetic_domain_graph()
    for entity in entities:
        repository.insert(entity)
    migrated_session.commit()
    migrated_session.expunge_all()

    assert repository.get(Ship, SHIP_ID) == entities[0]
    assert repository.get(ShipSystem, SYSTEM_ID) == entities[1]
    assert repository.get(Drawing, DRAWING_ID) == entities[2]
    assert repository.get(Equipment, EQUIPMENT_ID) == entities[3]
    assert repository.get(Material, MATERIAL_ID) == entities[4]
    assert repository.get(Supplier, SUPPLIER_ID) == entities[5]
    assert repository.get(BOMItem, BOM_ITEM_ID) == entities[6]
    assert repository.get(PurchaseOrder, PURCHASE_ORDER_ID) == entities[7]
    assert repository.get(ProjectTask, PROJECT_TASK_ID) == entities[8]

    loaded_po = repository.get(PurchaseOrder, PURCHASE_ORDER_ID)
    assert loaded_po is not None
    assert loaded_po.actual_date < loaded_po.promised_date < loaded_po.required_date
    assert loaded_po.quantity == PositiveQuantity(Decimal("20.125000"))
    assert loaded_po.id != loaded_po.source_id


def test_repository_get_returns_none_for_missing_canonical_id(
    migrated_session: Session,
) -> None:
    from infra.postgres.repositories import DomainRepository

    repository = DomainRepository(migrated_session)

    assert repository.get(Ship, UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")) is None
```

- [ ] **Step 2: Run focused repository tests and confirm RED**

Run:

```bash
TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_domain_repository.py::test_repository_round_trips_complete_synthetic_domain_graph \
  tests/integration/test_domain_repository.py::test_repository_get_returns_none_for_missing_canonical_id \
  -v
```

Expected: both fail with
`ModuleNotFoundError: No module named 'infra.postgres.repositories'`.

- [ ] **Step 3: Implement explicit model/domain conversion and repository behavior**

Create `infra/postgres/repositories.py`:

```python
"""Minimal SQLAlchemy repository for immutable canonical domain entities."""

from datetime import datetime
from typing import TypedDict, TypeVar, cast
from uuid import UUID

from sqlalchemy.orm import Session

from infra.postgres.models import (
    BOMItemModel,
    DrawingModel,
    EquipmentModel,
    MaterialModel,
    ProjectTaskModel,
    PurchaseOrderModel,
    ShipModel,
    ShipSystemModel,
    SupplierModel,
    _SourcedModel,
)
from packages.domain import (
    BOMItem,
    Drawing,
    Equipment,
    Material,
    PositiveQuantity,
    Progress,
    ProjectTask,
    PurchaseOrder,
    Ship,
    ShipSystem,
    Supplier,
)


type DomainEntity = (
    Ship
    | ShipSystem
    | Drawing
    | Equipment
    | Material
    | BOMItem
    | Supplier
    | PurchaseOrder
    | ProjectTask
)

EntityT = TypeVar(
    "EntityT",
    Ship,
    ShipSystem,
    Drawing,
    Equipment,
    Material,
    BOMItem,
    Supplier,
    PurchaseOrder,
    ProjectTask,
)


class UnsupportedDomainEntityError(TypeError):
    """Raised for an entity type outside the Task 005 domain set."""


_MODEL_BY_ENTITY: dict[type[object], type[_SourcedModel]] = {
    Ship: ShipModel,
    ShipSystem: ShipSystemModel,
    Drawing: DrawingModel,
    Equipment: EquipmentModel,
    Material: MaterialModel,
    BOMItem: BOMItemModel,
    Supplier: SupplierModel,
    PurchaseOrder: PurchaseOrderModel,
    ProjectTask: ProjectTaskModel,
}


class _SourceValues(TypedDict):
    id: UUID
    source_system: str
    source_id: str
    source_updated_at: datetime


def _source_values(entity: DomainEntity) -> _SourceValues:
    return {
        "id": entity.id,
        "source_system": entity.source_system,
        "source_id": entity.source_id,
        "source_updated_at": entity.source_updated_at,
    }


def _to_model(entity: DomainEntity) -> _SourcedModel:
    source = _source_values(entity)
    match entity:
        case Ship():
            return ShipModel(
                **source,
                ship_code=entity.ship_code,
                name=entity.name,
                customer_name=entity.customer_name,
                vessel_type=entity.vessel_type,
                planned_delivery_date=entity.planned_delivery_date,
            )
        case ShipSystem():
            return ShipSystemModel(
                **source,
                ship_id=entity.ship_id,
                system_code=entity.system_code,
                name=entity.name,
            )
        case Drawing():
            return DrawingModel(
                **source,
                ship_id=entity.ship_id,
                system_id=entity.system_id,
                drawing_no=entity.drawing_no,
                title=entity.title,
                revision=entity.revision,
                status=entity.status,
            )
        case Equipment():
            return EquipmentModel(
                **source,
                ship_id=entity.ship_id,
                system_id=entity.system_id,
                drawing_id=entity.drawing_id,
                equipment_code=entity.equipment_code,
                manufacturer=entity.manufacturer,
                model=entity.model,
            )
        case Material():
            return MaterialModel(
                **source,
                material_code=entity.material_code,
                description=entity.description,
                specification=entity.specification,
                unit=entity.unit,
            )
        case BOMItem():
            return BOMItemModel(
                **source,
                drawing_id=entity.drawing_id,
                equipment_id=entity.equipment_id,
                material_id=entity.material_id,
                quantity=entity.quantity.value,
            )
        case Supplier():
            return SupplierModel(
                **source,
                supplier_code=entity.supplier_code,
                canonical_name=entity.canonical_name,
            )
        case PurchaseOrder():
            return PurchaseOrderModel(
                **source,
                ship_id=entity.ship_id,
                material_id=entity.material_id,
                equipment_id=entity.equipment_id,
                supplier_id=entity.supplier_id,
                po_number=entity.po_number,
                quantity=(entity.quantity.value if entity.quantity else None),
                required_date=entity.required_date,
                promised_date=entity.promised_date,
                actual_date=entity.actual_date,
                status=entity.status,
                criticality=entity.criticality,
            )
        case ProjectTask():
            return ProjectTaskModel(
                **source,
                ship_id=entity.ship_id,
                task_code=entity.task_code,
                name=entity.name,
                planned_start=entity.planned_start,
                planned_end=entity.planned_end,
                actual_start=entity.actual_start,
                actual_end=entity.actual_end,
                planned_progress=(
                    entity.planned_progress.value
                    if entity.planned_progress
                    else None
                ),
                actual_progress=(
                    entity.actual_progress.value if entity.actual_progress else None
                ),
                critical_path=entity.critical_path,
            )
    raise UnsupportedDomainEntityError("unsupported domain entity type")


def _to_domain(model: _SourcedModel) -> DomainEntity:
    source: _SourceValues = {
        "id": model.id,
        "source_system": model.source_system,
        "source_id": model.source_id,
        "source_updated_at": model.source_updated_at,
    }
    match model:
        case ShipModel():
            return Ship(
                **source,
                ship_code=model.ship_code,
                name=model.name,
                customer_name=model.customer_name,
                vessel_type=model.vessel_type,
                planned_delivery_date=model.planned_delivery_date,
            )
        case ShipSystemModel():
            return ShipSystem(
                **source,
                ship_id=model.ship_id,
                system_code=model.system_code,
                name=model.name,
            )
        case DrawingModel():
            return Drawing(
                **source,
                ship_id=model.ship_id,
                system_id=model.system_id,
                drawing_no=model.drawing_no,
                title=model.title,
                revision=model.revision,
                status=model.status,
            )
        case EquipmentModel():
            return Equipment(
                **source,
                ship_id=model.ship_id,
                system_id=model.system_id,
                drawing_id=model.drawing_id,
                equipment_code=model.equipment_code,
                manufacturer=model.manufacturer,
                model=model.model,
            )
        case MaterialModel():
            return Material(
                **source,
                material_code=model.material_code,
                description=model.description,
                specification=model.specification,
                unit=model.unit,
            )
        case BOMItemModel():
            return BOMItem(
                **source,
                drawing_id=model.drawing_id,
                equipment_id=model.equipment_id,
                material_id=model.material_id,
                quantity=PositiveQuantity(model.quantity),
            )
        case SupplierModel():
            return Supplier(
                **source,
                supplier_code=model.supplier_code,
                canonical_name=model.canonical_name,
            )
        case PurchaseOrderModel():
            return PurchaseOrder(
                **source,
                ship_id=model.ship_id,
                material_id=model.material_id,
                equipment_id=model.equipment_id,
                supplier_id=model.supplier_id,
                po_number=model.po_number,
                quantity=(
                    PositiveQuantity(model.quantity)
                    if model.quantity is not None
                    else None
                ),
                required_date=model.required_date,
                promised_date=model.promised_date,
                actual_date=model.actual_date,
                status=model.status,
                criticality=model.criticality,
            )
        case ProjectTaskModel():
            return ProjectTask(
                **source,
                ship_id=model.ship_id,
                task_code=model.task_code,
                name=model.name,
                planned_start=model.planned_start,
                planned_end=model.planned_end,
                actual_start=model.actual_start,
                actual_end=model.actual_end,
                planned_progress=(
                    Progress(model.planned_progress)
                    if model.planned_progress is not None
                    else None
                ),
                actual_progress=(
                    Progress(model.actual_progress)
                    if model.actual_progress is not None
                    else None
                ),
                critical_path=model.critical_path,
            )
    raise UnsupportedDomainEntityError("unsupported persistence model type")


class DomainRepository:
    """Insert and load immutable domain entities in a caller-owned session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def insert(self, entity: DomainEntity) -> None:
        model = _to_model(entity)
        with self._session.begin_nested():
            self._session.add(model)
            self._session.flush()

    def get(
        self,
        entity_type: type[EntityT],
        entity_id: UUID,
    ) -> EntityT | None:
        model_type = _MODEL_BY_ENTITY.get(entity_type)
        if model_type is None:
            raise UnsupportedDomainEntityError("unsupported domain entity type")
        model = self._session.get(model_type, entity_id)
        if model is None:
            return None
        return cast(EntityT, _to_domain(model))
```

Replace `infra/postgres/__init__.py` with:

```python
"""PostgreSQL persistence infrastructure."""

from infra.postgres.models import Base
from infra.postgres.repositories import (
    DomainRepository,
    UnsupportedDomainEntityError,
)

__all__ = [
    "Base",
    "DomainRepository",
    "UnsupportedDomainEntityError",
]
```

- [ ] **Step 4: Run repository GREEN and all PostgreSQL integration tests**

Run:

```bash
TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_domain_repository.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  infra tests/integration/test_domain_repository.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  infra tests/integration/test_domain_repository.py
```

Expected: seven tests pass; Ruff and mypy pass. The round-trip equality proves
that every source, relationship, optional, date, Decimal, progress, and Boolean
field survives persistence.

- [ ] **Step 5: Commit the repository slice**

```bash
git add infra/postgres/__init__.py infra/postgres/repositories.py \
  tests/integration/test_domain_repository.py
git commit -m "feat: add typed domain repository"
```

---

### Task 4: Safe Integrity Errors and Executable Database Constraints

**Files:**
- Modify: `infra/postgres/repositories.py`
- Modify: `infra/postgres/__init__.py`
- Modify: `tests/integration/test_domain_repository.py`

**Interfaces:**
- Consumes: `DomainRepository`, all Task 1 constraints, and the migrated PostgreSQL fixture.
- Produces: safe `DomainPersistenceError` translation for unique, foreign-key, and check violations while leaving the caller-owned Session usable.

- [ ] **Step 1: Add failing repository error tests**

Add these imports to `tests/integration/test_domain_repository.py`:

```python
from typing import Any, cast

from sqlalchemy.exc import IntegrityError
```

Add:

```python
def test_repository_translates_duplicate_source_identity_without_value_leak(
    migrated_session: Session,
) -> None:
    from infra.postgres.repositories import (
        DomainPersistenceError,
        DomainRepository,
    )

    repository = DomainRepository(migrated_session)
    first = _synthetic_domain_graph()[0]
    repository.insert(first)
    migrated_session.commit()

    sensitive_source_id = first.source_id
    duplicate = Ship(
        **_source_fields(
            UUID("20000000-0000-0000-0000-000000000001"),
            sensitive_source_id,
        ),
        ship_code="SHIP-002",
    )

    with pytest.raises(DomainPersistenceError) as captured:
        repository.insert(duplicate)

    assert str(captured.value) == "domain entity violates persistence constraints"
    assert sensitive_source_id not in str(captured.value)
    assert repository.get(Ship, first.id) == first


def test_repository_translates_foreign_key_failure_and_preserves_session(
    migrated_session: Session,
) -> None:
    from infra.postgres.repositories import (
        DomainPersistenceError,
        DomainRepository,
    )

    repository = DomainRepository(migrated_session)
    invalid_system = ShipSystem(
        **_source_fields(
            UUID("20000000-0000-0000-0000-000000000002"),
            "missing-ship-system",
        ),
        ship_id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
        system_code="SYS-MISSING",
        name="Synthetic missing system",
    )

    with pytest.raises(
        DomainPersistenceError,
        match="^domain entity violates persistence constraints$",
    ):
        repository.insert(invalid_system)

    valid_ship = _synthetic_domain_graph()[0]
    repository.insert(valid_ship)
    assert repository.get(Ship, valid_ship.id) == valid_ship


def test_repository_rejects_types_outside_task_005(migrated_session: Session) -> None:
    from infra.postgres.repositories import (
        DomainRepository,
        UnsupportedDomainEntityError,
    )

    repository = DomainRepository(migrated_session)

    with pytest.raises(
        UnsupportedDomainEntityError,
        match="^unsupported domain entity type$",
    ):
        repository.insert(cast(Any, object()))
    with pytest.raises(
        UnsupportedDomainEntityError,
        match="^unsupported domain entity type$",
    ):
        repository.get(cast(Any, str), SHIP_ID)
```

- [ ] **Step 2: Run the safe-error tests and confirm RED**

Run:

```bash
TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_domain_repository.py::test_repository_translates_duplicate_source_identity_without_value_leak \
  tests/integration/test_domain_repository.py::test_repository_translates_foreign_key_failure_and_preserves_session \
  -v
```

Expected: FAIL because Task 3 exposes SQLAlchemy `IntegrityError` rather than
the not-yet-defined `DomainPersistenceError`.

- [ ] **Step 3: Implement minimum safe error translation**

In `infra/postgres/repositories.py`, import:

```python
from sqlalchemy.exc import IntegrityError
```

Add before `UnsupportedDomainEntityError`:

```python
class DomainPersistenceError(RuntimeError):
    """Raised when a domain entity violates persistence constraints."""
```

Replace `DomainRepository.insert` with:

```python
    def insert(self, entity: DomainEntity) -> None:
        model = _to_model(entity)
        try:
            with self._session.begin_nested():
                self._session.add(model)
                self._session.flush()
        except IntegrityError:
            raise DomainPersistenceError(
                "domain entity violates persistence constraints"
            ) from None
```

Export `DomainPersistenceError` from `infra/postgres/__init__.py` by adding it
to both the repository import block and `__all__`.

- [ ] **Step 4: Add real PostgreSQL CHECK-constraint execution tests**

Add this exact factory and parameterized test to
`tests/integration/test_domain_repository.py`:

```python
def _invalid_persistence_model(case: str) -> object:
    from infra.postgres.models import (
        BOMItemModel,
        MaterialModel,
        ProjectTaskModel,
        PurchaseOrderModel,
        ShipModel,
    )

    entity_id = UUID(
        {
            "blank_source": "30000000-0000-0000-0000-000000000001",
            "blank_text": "30000000-0000-0000-0000-000000000002",
            "bom_target": "30000000-0000-0000-0000-000000000003",
            "bom_zero": "30000000-0000-0000-0000-000000000004",
            "bom_nan": "30000000-0000-0000-0000-000000000005",
            "po_target": "30000000-0000-0000-0000-000000000006",
            "po_blank_optional": "30000000-0000-0000-0000-000000000007",
            "task_dates": "30000000-0000-0000-0000-000000000008",
            "task_progress": "30000000-0000-0000-0000-000000000009",
            "task_nan": "30000000-0000-0000-0000-000000000010",
        }[case]
    )
    source = _source_fields(entity_id, f"invalid-{case}")
    if case == "blank_source":
        return ShipModel(
            id=entity_id,
            source_system=" ",
            source_id=source["source_id"],
            source_updated_at=SOURCE_UPDATED_AT,
            ship_code="SHIP-INVALID-SOURCE",
        )
    if case == "blank_text":
        return MaterialModel(
            **source,
            material_code="MAT-INVALID-TEXT",
            description=" ",
        )
    if case == "bom_target":
        return BOMItemModel(
            **source,
            drawing_id=None,
            equipment_id=None,
            material_id=MATERIAL_ID,
            quantity=Decimal("1"),
        )
    if case == "bom_zero":
        return BOMItemModel(
            **source,
            drawing_id=DRAWING_ID,
            equipment_id=None,
            material_id=MATERIAL_ID,
            quantity=Decimal("0"),
        )
    if case == "bom_nan":
        return BOMItemModel(
            **source,
            drawing_id=DRAWING_ID,
            equipment_id=None,
            material_id=MATERIAL_ID,
            quantity=Decimal("NaN"),
        )
    if case == "po_target":
        return PurchaseOrderModel(
            **source,
            ship_id=SHIP_ID,
            material_id=None,
            equipment_id=None,
            supplier_id=SUPPLIER_ID,
            po_number="PO-INVALID-TARGET",
            status="OPEN",
        )
    if case == "po_blank_optional":
        return PurchaseOrderModel(
            **source,
            ship_id=SHIP_ID,
            material_id=MATERIAL_ID,
            equipment_id=None,
            supplier_id=SUPPLIER_ID,
            po_number="PO-INVALID-TEXT",
            status="OPEN",
            criticality=" ",
        )
    if case == "task_dates":
        return ProjectTaskModel(
            **source,
            ship_id=SHIP_ID,
            task_code="TASK-INVALID-DATES",
            name="Invalid date range",
            planned_start=date(2027, 2, 1),
            planned_end=date(2027, 1, 1),
        )
    if case == "task_progress":
        return ProjectTaskModel(
            **source,
            ship_id=SHIP_ID,
            task_code="TASK-INVALID-PROGRESS",
            name="Invalid progress",
            planned_progress=Decimal("1.1"),
        )
    if case == "task_nan":
        return ProjectTaskModel(
            **source,
            ship_id=SHIP_ID,
            task_code="TASK-NAN-PROGRESS",
            name="NaN progress",
            actual_progress=Decimal("NaN"),
        )
    raise AssertionError("unhandled constraint case")


@pytest.mark.parametrize(
    "case",
    [
        "blank_source",
        "blank_text",
        "bom_target",
        "bom_zero",
        "bom_nan",
        "po_target",
        "po_blank_optional",
        "task_dates",
        "task_progress",
        "task_nan",
    ],
)
def test_postgresql_rejects_domain_constraint_violations(
    migrated_session: Session,
    case: str,
) -> None:
    from infra.postgres.repositories import DomainRepository

    repository = DomainRepository(migrated_session)
    for entity in _synthetic_domain_graph()[:6]:
        repository.insert(entity)
    migrated_session.commit()

    with pytest.raises(IntegrityError):
        with migrated_session.begin_nested():
            migrated_session.add(_invalid_persistence_model(case))
            migrated_session.flush()
```

These tests insert invalid ORM rows intentionally to prove PostgreSQL enforces
the approved domain rules even when no domain constructor is involved.

- [ ] **Step 5: Run GREEN, the whole repository module, Ruff, and mypy**

Run:

```bash
TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_domain_repository.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  infra tests/integration/test_domain_repository.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  infra tests/integration/test_domain_repository.py
```

Expected: all repository/migration cases pass, including ten executed
PostgreSQL constraint cases; Ruff and mypy pass.

- [ ] **Step 6: Commit constraint and error coverage**

```bash
git add infra/postgres/__init__.py infra/postgres/repositories.py \
  tests/integration/test_domain_repository.py
git commit -m "test: enforce domain persistence constraints"
```

---

### Task 5: Runtime Packaging, Operator Documentation, and Final Gate

**Files:**
- Modify: `pyproject.toml`
- Modify: `Dockerfile`
- Modify: `tests/integration/test_deployment.py`
- Modify: `infra/postgres/README.md`

**Interfaces:**
- Consumes: the completed `infra.postgres` public API, Alembic revision, and CI PostgreSQL service.
- Produces: an installable/importable infrastructure package and documented migration/test operations.

- [ ] **Step 1: Write failing deployment packaging coverage**

In `tests/integration/test_deployment.py`, add:

```python
def test_docker_build_inputs_include_postgres_migration_runtime(
    tmp_path: Path,
) -> None:
    build_context = tmp_path / "build-context"
    build_context.mkdir()

    _stage_docker_copy_inputs(build_context)

    assert build_context.joinpath("infra/postgres/models.py").is_file()
    assert build_context.joinpath("infra/postgres/repositories.py").is_file()
    assert build_context.joinpath("alembic.ini").is_file()
```

In `test_docker_build_inputs_install_runtime_package_artifact`, replace the
smoke command's Python source with:

```python
            "from adapters.auth.local import LocalAuthenticationAdapter; "
            "from infra.postgres import Base, DomainRepository; "
            "from packages.common.logging import REDACTED; "
            "from packages.contracts.auth import AuthorizationScope; "
            "from services.auth.service import authorization_scope_for; "
            "print(REDACTED, AuthorizationScope.__name__, "
            "LocalAuthenticationAdapter.__name__, authorization_scope_for.__name__, "
            "Base.__name__, DomainRepository.__name__)",
```

Replace its expected output with:

```python
    assert smoke.stdout.strip() == (
        "[REDACTED] AuthorizationScope LocalAuthenticationAdapter "
        "authorization_scope_for Base DomainRepository"
    )
```

- [ ] **Step 2: Run deployment tests and confirm RED**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_deployment.py::test_docker_build_inputs_include_postgres_migration_runtime \
  tests/integration/test_deployment.py::test_docker_build_inputs_install_runtime_package_artifact \
  -v
```

Expected: the first test fails because Docker does not copy `infra` or
`alembic.ini`; the artifact test fails because setuptools does not include
`infra*`.

- [ ] **Step 3: Package infrastructure in the wheel and Docker image**

Change the setuptools include list in `pyproject.toml` to:

```toml
include = ["adapters*", "apps*", "infra*", "packages*", "services*"]
```

In `Dockerfile`, add these inputs after the existing package/service copies and
before `RUN pip install`:

```dockerfile
COPY infra ./infra
COPY alembic.ini ./
```

- [ ] **Step 4: Document the exact persistence and test operations**

Append this section to `infra/postgres/README.md`:

````markdown
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
````

- [ ] **Step 5: Run focused deployment GREEN**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_deployment.py::test_docker_build_inputs_include_postgres_migration_runtime \
  tests/integration/test_deployment.py::test_docker_build_inputs_install_runtime_package_artifact \
  -v
```

Expected: both tests pass and the isolated installed artifact prints
`Base DomainRepository` at the end of its smoke output.

- [ ] **Step 6: Verify migration/metadata parity against PostgreSQL**

Run:

```bash
DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m alembic upgrade head
DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m alembic check
DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m alembic downgrade base
```

Expected: upgrade succeeds, `alembic check` reports no new upgrade operations,
and downgrade succeeds.

- [ ] **Step 7: Run the complete Task 006 verification gate**

Run:

```bash
TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_domain_repository.py -v
TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
make check PYTHON=/Users/wuhao/Documents/shipyard-ai/.venv/bin/python
DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m alembic upgrade head --sql
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check .
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy .
git diff --check origin/main...HEAD
```

Expected:

- all repository and migration integration tests pass against PostgreSQL;
- the full suite has 114 passing cases and no skips in CI-equivalent mode;
- Ruff passes;
- mypy passes;
- offline SQL generation contains all nine domain tables; and
- branch whitespace checks pass.

- [ ] **Step 8: Check Task 006 acceptance and scope**

Confirm from tests and the branch diff:

```text
PASS — canonical UUID columns are distinct from source identity columns
PASS — all documented foreign keys exist
PASS — repository integration tests use PostgreSQL through TEST_DATABASE_URL
PASS — Alembic upgrades from an empty test database
PASS — Task 005 domain imports remain framework-independent
PASS — no EntityAlias or Task 007 implementation exists
PASS — no real credentials or customer data are present
```

- [ ] **Step 9: Commit documentation and packaging**

```bash
git add Dockerfile infra/postgres/README.md pyproject.toml \
  tests/integration/test_deployment.py
git commit -m "build: package domain persistence runtime"
```

- [ ] **Step 10: Independent review and final acceptance**

Request a read-only review of `origin/main...HEAD` against `AGENTS.md`,
`tasks/006-domain-persistence.md`, and the approved design. Resolve every P0,
P1, and P2 finding with focused regression tests and re-review. Re-run Step 7
fresh after the final reviewed fix before reporting completion.

Do not start Task 007.

---
