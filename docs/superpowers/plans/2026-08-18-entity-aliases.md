# Task 007 Entity Aliases Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic, explicitly registered Supplier, Equipment, and Material aliases with PostgreSQL referential integrity and scope-safe exact resolution.

**Architecture:** Keep normalization and the immutable alias type in the framework-independent domain package. Persist aliases in one PostgreSQL table with three typed foreign keys, expose a caller-transaction-owned exact lookup repository, and enforce global-versus-ship authorization in a service that depends on protocols/callables rather than SQLAlchemy.

**Tech Stack:** Python 3.12.13, dataclasses, Unicode standard library, Pydantic 2.x authorization contracts, SQLAlchemy 2.x, Alembic, PostgreSQL 16, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-18-entity-aliases-design.md`

## Global Constraints

- Implement Task 007 only; do not create Task 008 fixtures, an API endpoint, an Agent tool, a fuzzy matcher, or an alias approval UI.
- `packages/domain` remains framework-independent and imports only the Python standard library and domain-local modules.
- Supported alias entity types are exactly `supplier`, `equipment`, and `material`.
- Canonical UUIDs remain distinct from source-system IDs; an alias never replaces or mutates a canonical entity.
- Every semantic variant is explicitly registered. Normalization uses NFKC, `casefold`, and whitespace collapse but does not strip accents, punctuation, or transliterate scripts.
- `Wärtsilä`, `Wartsila`, and `瓦锡兰` remain distinct alias keys and resolve through three explicit rows to one canonical Supplier.
- `Wartsilla` and every other unregistered near-spelling return `None`; no candidate is generated and no merge occurs.
- PostgreSQL enforces exactly one typed canonical FK on each alias row with default `NO ACTION` behavior.
- Global uniqueness is `(entity_type, normalized_alias)` where `source_system IS NULL`; source-specific uniqueness is `(entity_type, source_system, normalized_alias)` where `source_system IS NOT NULL`.
- A source-specific lookup tries that exact source first and then the global alias. A lookup without a source sees only global aliases.
- `AliasRepository` never commits, retries, updates, deletes, merges, or upserts; the caller owns the Session and outer transaction.
- Persistence errors use fixed text and never contain rejected alias values, SQL, or credentials.
- Authorization is enforced in `services.entity_resolution`: Supplier/Material aliases are authenticated global master data; Equipment aliases require the canonical equipment's `ship_id` in the server-derived allowed ship scope.
- Missing and unauthorized Equipment aliases both return `None`.
- Tests use deterministic synthetic data, no network calls, and no external models.
- PostgreSQL integration tests read only guarded `TEST_DATABASE_URL` and destructive migration operations remain restricted to exact database `shipyard_ai_test`.
- Migration revision is exactly `20260818_0002` with parent `20260817_0001`.

---

### Task 1: Immutable Alias Domain and Deterministic Normalization

**Files:**
- Create: `packages/domain/aliases.py`
- Modify: `packages/domain/__init__.py`
- Create: `tests/unit/test_entity_aliases.py`

**Interfaces:**
- Consumes: `DomainValidationError` from `packages.domain.value_objects`.
- Produces: `AliasEntityType`, `EntityAlias`, and `normalize_alias(value: str) -> str`.

- [ ] **Step 1: Write the failing domain tests**

Create `tests/unit/test_entity_aliases.py`:

```python
from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from packages.domain import DomainValidationError


ALIAS_ID = UUID("70000000-0000-0000-0000-000000000001")
SUPPLIER_ID = UUID("70000000-0000-0000-0000-000000000002")


def test_explicit_brand_variants_keep_distinct_normalized_keys() -> None:
    from packages.domain.aliases import normalize_alias

    assert normalize_alias("Wärtsilä") == "wärtsilä"
    assert normalize_alias("Wartsila") == "wartsila"
    assert normalize_alias("瓦锡兰") == "瓦锡兰"
    assert len(
        {
            normalize_alias("Wärtsilä"),
            normalize_alias("Wartsila"),
            normalize_alias("瓦锡兰"),
        }
    ) == 3


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  WARTSILA  ", "wartsila"),
        ("ＷＡＲＴＳＩＬＡ", "wartsila"),
        ("Main\t Cooling\n Pump", "main cooling pump"),
    ],
)
def test_normalize_alias_handles_case_width_and_whitespace(
    raw: str,
    expected: str,
) -> None:
    from packages.domain.aliases import normalize_alias

    assert normalize_alias(raw) == expected


@pytest.mark.parametrize("value", ["", "  \t\n  ", 123])
def test_normalize_alias_rejects_blank_or_non_text_without_value_leak(
    value: object,
) -> None:
    from packages.domain.aliases import normalize_alias

    with pytest.raises(DomainValidationError) as captured:
        normalize_alias(value)  # type: ignore[arg-type]

    assert str(captured.value) == "alias must be non-blank text"
    assert repr(value) not in str(captured.value)


def test_entity_alias_is_frozen_and_computes_its_normalized_key() -> None:
    from packages.domain.aliases import AliasEntityType, EntityAlias

    alias = EntityAlias(
        id=ALIAS_ID,
        entity_type=AliasEntityType.SUPPLIER,
        entity_id=SUPPLIER_ID,
        alias="  Wärtsilä  ",
        source_system="erp-a",
    )

    assert alias.normalized_alias == "wärtsilä"
    with pytest.raises(FrozenInstanceError):
        alias.alias = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "not-a-uuid"},
        {"entity_id": "not-a-uuid"},
        {"entity_type": "supplier"},
        {"source_system": "   "},
    ],
)
def test_entity_alias_rejects_invalid_fields(overrides: dict[str, object]) -> None:
    from packages.domain.aliases import AliasEntityType, EntityAlias

    values: dict[str, object] = {
        "id": ALIAS_ID,
        "entity_type": AliasEntityType.SUPPLIER,
        "entity_id": SUPPLIER_ID,
        "alias": "Wärtsilä",
        "source_system": None,
    }
    values.update(overrides)

    with pytest.raises(DomainValidationError):
        EntityAlias(**values)  # type: ignore[arg-type]
```

- [ ] **Step 2: Run the domain tests and confirm RED**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/test_entity_aliases.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named
'packages.domain.aliases'`.

- [ ] **Step 3: Implement the minimal domain model**

Create `packages/domain/aliases.py`:

```python
"""Immutable explicit aliases for canonical shipyard entities."""

from dataclasses import dataclass, field
from enum import StrEnum
from unicodedata import normalize
from uuid import UUID

from packages.domain.value_objects import DomainValidationError


class AliasEntityType(StrEnum):
    """Canonical entity types supported by explicit alias resolution."""

    SUPPLIER = "supplier"
    EQUIPMENT = "equipment"
    MATERIAL = "material"


def normalize_alias(value: str) -> str:
    """Return the deterministic exact-lookup key for an explicit alias."""
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError("alias must be non-blank text")
    return " ".join(normalize("NFKC", value).casefold().split())


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityAlias:
    """An explicit textual link to one canonical entity UUID."""

    id: UUID
    entity_type: AliasEntityType
    entity_id: UUID
    alias: str
    source_system: str | None = None
    normalized_alias: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise DomainValidationError("id must be a UUID")
        if not isinstance(self.entity_type, AliasEntityType):
            raise DomainValidationError("entity_type is unsupported")
        if not isinstance(self.entity_id, UUID):
            raise DomainValidationError("entity_id must be a UUID")
        if self.source_system is not None and (
            not isinstance(self.source_system, str) or not self.source_system.strip()
        ):
            raise DomainValidationError(
                "source_system must be non-blank when provided"
            )
        object.__setattr__(self, "normalized_alias", normalize_alias(self.alias))
```

Update `packages/domain/__init__.py` with:

```python
from packages.domain.aliases import AliasEntityType, EntityAlias, normalize_alias
```

and add these exact entries to `__all__` in alphabetical order:

```python
    "AliasEntityType",
    "EntityAlias",
    "normalize_alias",
```

- [ ] **Step 4: Run GREEN and domain-package static checks**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/test_entity_aliases.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  packages/domain tests/unit/test_entity_aliases.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  packages/domain tests/unit/test_entity_aliases.py
```

Expected: all alias-domain tests pass; Ruff and mypy pass.

- [ ] **Step 5: Commit the domain slice**

```bash
git add packages/domain/aliases.py packages/domain/__init__.py \
  tests/unit/test_entity_aliases.py
git commit -m "feat: add entity alias domain model"
```

---

### Task 2: Shared PostgreSQL Harness, Alias Metadata, and Alembic Revision

**Files:**
- Create: `tests/integration/postgres_support.py`
- Create: `tests/integration/conftest.py`
- Modify: `tests/integration/test_domain_repository.py`
- Modify: `infra/postgres/models.py`
- Create: `infra/postgres/migrations/versions/20260818_0002_create_entity_aliases.py`
- Create: `tests/integration/test_entity_alias_repository.py`

**Interfaces:**
- Consumes: Task 1 `AliasEntityType`; Task 006 `Base`, protected Alembic config, and caller-owned Session pattern.
- Produces: `EntityAliasModel`, shared `migrated_engine`/`migrated_session` fixtures, and Alembic head `20260818_0002`.

- [ ] **Step 1: Extract the existing protected PostgreSQL harness without changing behavior**

Create `tests/integration/postgres_support.py` by moving the current
`REPOSITORY_ROOT`, `EXPLICIT_DATABASE_URL_ATTRIBUTE`, URL validation, Alembic
configuration, effective-target validation, and guarded downgrade functions
from `test_domain_repository.py`. Keep their exact fixed error messages and
rename only the module-private call sites to public test-support names:

```python
"""Shared protected PostgreSQL integration-test operations."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL, make_url

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXPLICIT_DATABASE_URL_ATTRIBUTE = "shipyard_ai_explicit_database_url"


def validated_test_database_url(raw_url: str) -> URL:
    url = make_url(raw_url)
    if url.database is None or not url.database.endswith("_test"):
        raise ValueError("TEST_DATABASE_URL must name a database ending in _test")
    return url


def configured_test_database_url() -> URL:
    raw_url = os.getenv("TEST_DATABASE_URL")
    if raw_url is None:
        pytest.skip("TEST_DATABASE_URL is not configured")
    try:
        return validated_test_database_url(raw_url)
    except ValueError as exc:
        pytest.fail(str(exc), pytrace=False)


def alembic_config(url: URL) -> Config:
    config = Config(str(REPOSITORY_ROOT / "alembic.ini"))
    rendered_url = url.render_as_string(hide_password=False).replace("%", "%%")
    config.set_main_option("sqlalchemy.url", rendered_url)
    config.attributes[EXPLICIT_DATABASE_URL_ATTRIBUTE] = True
    return config


def validated_alembic_test_database_url(config: Config) -> URL:
    raw_url = config.get_main_option("sqlalchemy.url")
    if raw_url is None:
        raise ValueError("Alembic must have an explicitly configured test database")
    url = validated_test_database_url(raw_url)
    if url.database != "shipyard_ai_test":
        raise ValueError("Alembic must target database shipyard_ai_test")
    return url


def downgrade_to_base(config: Config) -> None:
    validated_alembic_test_database_url(config)
    command.downgrade(config, "base")
```

Create `tests/integration/conftest.py`:

```python
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.integration.postgres_support import (
    alembic_config,
    configured_test_database_url,
    downgrade_to_base,
)


@pytest.fixture()
def migrated_engine() -> Iterator[Engine]:
    url = configured_test_database_url()
    config = alembic_config(url)
    downgrade_to_base(config)
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()
        downgrade_to_base(config)


@pytest.fixture()
def migrated_session(migrated_engine: Engine) -> Iterator[Session]:
    with Session(migrated_engine) as session:
        yield session
```

Modify `test_domain_repository.py` to import the exact support names:

```python
from tests.integration.postgres_support import (
    alembic_config,
    configured_test_database_url,
    downgrade_to_base,
    validated_alembic_test_database_url,
    validated_test_database_url,
)
```

Delete its local URL/Alembic helpers and fixtures, then replace call sites
exactly as follows (test behavior and fixed messages stay unchanged):

```text
_validated_test_database_url         -> validated_test_database_url
_configured_test_database_url        -> configured_test_database_url
_alembic_config                      -> alembic_config
_validated_alembic_test_database_url -> validated_alembic_test_database_url
_downgrade_to_base                   -> downgrade_to_base
```

Run the existing module before continuing:

```bash
TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_domain_repository.py -v
```

Expected: the pre-Task-007 22 cases remain green.

- [ ] **Step 2: Add failing metadata and migration-head tests**

Create `tests/integration/test_entity_alias_repository.py` with:

```python
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, inspect, text
from sqlalchemy.engine import Engine


ALIAS_TABLE = "entity_aliases"
ALIAS_ID = UUID("71000000-0000-0000-0000-000000000001")
SHIP_ID = UUID("71000000-0000-0000-0000-000000000002")
EQUIPMENT_ID = UUID("71000000-0000-0000-0000-000000000003")
MATERIAL_ID = UUID("71000000-0000-0000-0000-000000000004")
SUPPLIER_ID = UUID("71000000-0000-0000-0000-000000000005")


def test_alias_metadata_declares_typed_targets_and_lookup_constraints() -> None:
    from infra.postgres.models import Base

    table = Base.metadata.tables[ALIAS_TABLE]
    assert {
        "id",
        "entity_type",
        "alias",
        "normalized_alias",
        "source_system",
        "supplier_id",
        "equipment_id",
        "material_id",
    } == {column.name for column in table.columns}
    assert {
        column.name: next(iter(column.foreign_keys)).target_fullname
        for column in table.columns
        if column.foreign_keys
    } == {
        "supplier_id": "suppliers.id",
        "equipment_id": "equipment.id",
        "material_id": "materials.id",
    }
    check_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_entity_aliases_alias",
        "ck_entity_aliases_normalized_alias",
        "ck_entity_aliases_source_system",
        "ck_entity_aliases_target",
    } <= check_names
    assert {
        index.name
        for index in table.indexes
        if isinstance(index, Index)
    } >= {
        "uq_entity_aliases_global_lookup",
        "uq_entity_aliases_source_lookup",
        "ix_entity_aliases_supplier_id",
        "ix_entity_aliases_equipment_id",
        "ix_entity_aliases_material_id",
    }


def test_alias_migration_is_current_head(migrated_engine: Engine) -> None:
    assert ALIAS_TABLE in inspect(migrated_engine).get_table_names()
    with migrated_engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260818_0002"
```

In `test_domain_repository.py`, replace the exact metadata assertion/loop and
migration head with:

```python
assert DOMAIN_TABLES <= set(Base.metadata.tables)
for table_name in DOMAIN_TABLES:
    table = Base.metadata.tables[table_name]
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
```

```python
assert connection.execute(
    text("SELECT version_num FROM alembic_version")
).scalar_one() == "20260818_0002"
```

Do not add alias fields to the sourced-domain-table loop.

- [ ] **Step 3: Run the two new tests and confirm RED**

Run:

```bash
TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_entity_alias_repository.py::test_alias_metadata_declares_typed_targets_and_lookup_constraints \
  tests/integration/test_entity_alias_repository.py::test_alias_migration_is_current_head \
  -v
```

Expected: metadata test fails with missing `entity_aliases`; migration test
fails because head remains `20260817_0001` and the alias table is absent.

- [ ] **Step 4: Add exact SQLAlchemy metadata**

Add `Index` and `text` to the existing SQLAlchemy import list in
`infra/postgres/models.py`, then add:

```python
class EntityAliasModel(Base):
    __tablename__ = "entity_aliases"
    __table_args__ = (
        CheckConstraint("btrim(alias) <> ''", name="ck_entity_aliases_alias"),
        CheckConstraint(
            "btrim(normalized_alias) <> ''",
            name="ck_entity_aliases_normalized_alias",
        ),
        CheckConstraint(
            "source_system IS NULL OR btrim(source_system) <> ''",
            name="ck_entity_aliases_source_system",
        ),
        CheckConstraint(
            "(entity_type = 'supplier' AND supplier_id IS NOT NULL "
            "AND equipment_id IS NULL AND material_id IS NULL) OR "
            "(entity_type = 'equipment' AND supplier_id IS NULL "
            "AND equipment_id IS NOT NULL AND material_id IS NULL) OR "
            "(entity_type = 'material' AND supplier_id IS NULL "
            "AND equipment_id IS NULL AND material_id IS NOT NULL)",
            name="ck_entity_aliases_target",
        ),
        Index(
            "uq_entity_aliases_global_lookup",
            "entity_type",
            "normalized_alias",
            unique=True,
            postgresql_where=text("source_system IS NULL"),
        ),
        Index(
            "uq_entity_aliases_source_lookup",
            "entity_type",
            "source_system",
            "normalized_alias",
            unique=True,
            postgresql_where=text("source_system IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_alias: Mapped[str] = mapped_column(Text, nullable=False)
    source_system: Mapped[str | None] = mapped_column(Text)
    supplier_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("suppliers.id", name="fk_entity_aliases_supplier_id"),
        index=True,
    )
    equipment_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("equipment.id", name="fk_entity_aliases_equipment_id"),
        index=True,
    )
    material_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("materials.id", name="fk_entity_aliases_material_id"),
        index=True,
    )
```

- [ ] **Step 5: Generate and review exact revision `20260818_0002`**

First upgrade the protected test database to Task 006 head, then generate:

```bash
DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m alembic upgrade head
DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m alembic revision \
  --autogenerate --rev-id 20260818_0002 -m "create entity aliases"
```

Review the generated file and require:

```python
revision: str = "20260818_0002"
down_revision: str | Sequence[str] | None = "20260817_0001"
```

`upgrade()` must contain one explicit `op.create_table("entity_aliases", ...)`,
the four named CHECK constraints, three named FKs, two partial unique indexes,
and three FK indexes. `downgrade()` must drop those indexes and only
`entity_aliases`. Neither function may call metadata `create_all`/`drop_all` or
contain `pass`.

- [ ] **Step 6: Run migration GREEN and static checks**

```bash
TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_domain_repository.py \
  tests/integration/test_entity_alias_repository.py -v
DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m alembic upgrade head --sql
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  infra tests/integration
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  infra tests/integration
```

Expected: existing repository tests and both alias schema tests pass; offline
SQL contains `CREATE TABLE entity_aliases`; Ruff and mypy pass.

- [ ] **Step 7: Commit the schema slice**

```bash
git add infra/postgres/models.py \
  infra/postgres/migrations/versions/20260818_0002_create_entity_aliases.py \
  tests/integration/postgres_support.py tests/integration/conftest.py \
  tests/integration/test_domain_repository.py \
  tests/integration/test_entity_alias_repository.py
git commit -m "feat: add entity alias schema migration"
```

---

### Task 3: Exact Alias Repository and PostgreSQL Behavior

**Files:**
- Create: `infra/postgres/alias_repository.py`
- Modify: `infra/postgres/__init__.py`
- Modify: `tests/integration/test_entity_alias_repository.py`

**Interfaces:**
- Consumes: `EntityAlias`, `AliasEntityType`, `normalize_alias`, `EntityAliasModel`, and caller-owned `Session`.
- Produces: `AliasRepository.insert`, `AliasRepository.resolve`, and safe `AliasPersistenceError`.

- [ ] **Step 1: Add failing explicit-link and exact-lookup tests**

Extend the integration file with these deterministic builders (add the
corresponding `UTC`, `datetime`, `Equipment`, `Material`, `Ship`, and
`Supplier` imports):

```python
SOURCE_UPDATED_AT = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)


def _ship(entity_id: UUID) -> Ship:
    return Ship(
        id=entity_id,
        source_system="synthetic-source",
        source_id=f"ship-{entity_id}",
        source_updated_at=SOURCE_UPDATED_AT,
        ship_code=f"SHIP-{entity_id}",
    )


def _equipment(entity_id: UUID, ship_id: UUID) -> Equipment:
    return Equipment(
        id=entity_id,
        source_system="synthetic-source",
        source_id=f"equipment-{entity_id}",
        source_updated_at=SOURCE_UPDATED_AT,
        ship_id=ship_id,
        equipment_code=f"EQ-{entity_id}",
    )


def _material(entity_id: UUID, code: str) -> Material:
    return Material(
        id=entity_id,
        source_system="synthetic-source",
        source_id=f"material-{entity_id}",
        source_updated_at=SOURCE_UPDATED_AT,
        material_code=code,
        description=f"Synthetic material {code}",
    )


def _supplier(entity_id: UUID, source_id: str, code: str, name: str) -> Supplier:
    return Supplier(
        id=entity_id,
        source_system="synthetic-source",
        source_id=source_id,
        source_updated_at=SOURCE_UPDATED_AT,
        supplier_code=code,
        canonical_name=name,
    )
```

Use Task 006 `DomainRepository` to insert canonical rows. Add this explicit
supplier fixture behavior:

```python
def test_three_explicit_supplier_aliases_resolve_to_one_canonical_supplier(
    migrated_session: Session,
) -> None:
    from infra.postgres import AliasRepository, DomainRepository
    from packages.domain import AliasEntityType, EntityAlias

    supplier = _supplier(SUPPLIER_ID, "supplier-001", "SUP-001", "Wärtsilä")
    DomainRepository(migrated_session).insert(supplier)
    repository = AliasRepository(migrated_session)
    aliases = [
        EntityAlias(
            id=UUID("72000000-0000-0000-0000-000000000001"),
            entity_type=AliasEntityType.SUPPLIER,
            entity_id=supplier.id,
            alias="Wärtsilä",
        ),
        EntityAlias(
            id=UUID("72000000-0000-0000-0000-000000000002"),
            entity_type=AliasEntityType.SUPPLIER,
            entity_id=supplier.id,
            alias="Wartsila",
        ),
        EntityAlias(
            id=UUID("72000000-0000-0000-0000-000000000003"),
            entity_type=AliasEntityType.SUPPLIER,
            entity_id=supplier.id,
            alias="瓦锡兰",
        ),
    ]
    for alias in aliases:
        repository.insert(alias)
    migrated_session.commit()
    migrated_session.expunge_all()

    assert repository.resolve(AliasEntityType.SUPPLIER, "WÄRTSILÄ") == aliases[0]
    assert repository.resolve(AliasEntityType.SUPPLIER, "Wartsila") == aliases[1]
    assert repository.resolve(AliasEntityType.SUPPLIER, "瓦锡兰") == aliases[2]
    assert repository.resolve(AliasEntityType.SUPPLIER, "Wartsilla") is None
```

Add this source precedence test with global alias `Shared code` linked to
material A and source-specific `Shared code`/`erp-a` linked to material B:

```python
def test_source_specific_alias_precedes_global_without_crossing_sources(
    migrated_session: Session,
) -> None:
    from infra.postgres import AliasRepository, DomainRepository
    from packages.domain import AliasEntityType, EntityAlias

    material_a = _material(MATERIAL_ID, "MAT-A")
    material_b = _material(
        UUID("71000000-0000-0000-0000-000000000006"), "MAT-B"
    )
    domain_repository = DomainRepository(migrated_session)
    domain_repository.insert(material_a)
    domain_repository.insert(material_b)
    repository = AliasRepository(migrated_session)
    global_alias = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000004"),
        entity_type=AliasEntityType.MATERIAL,
        entity_id=material_a.id,
        alias="Shared code",
    )
    source_alias = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000005"),
        entity_type=AliasEntityType.MATERIAL,
        entity_id=material_b.id,
        alias="Shared code",
        source_system="erp-a",
    )
    source_only_alias = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000010"),
        entity_type=AliasEntityType.MATERIAL,
        entity_id=material_b.id,
        alias="Source only code",
        source_system="erp-a",
    )
    repository.insert(global_alias)
    repository.insert(source_alias)
    repository.insert(source_only_alias)
    migrated_session.commit()

    assert repository.resolve(AliasEntityType.MATERIAL, "shared code") == global_alias
    assert repository.resolve(
        AliasEntityType.MATERIAL, "shared code", "erp-a"
    ) == source_alias
    assert repository.resolve(
        AliasEntityType.MATERIAL, "shared code", "erp-b"
    ) == global_alias
    assert repository.resolve(AliasEntityType.MATERIAL, "source only code") is None
    assert repository.resolve(
        AliasEntityType.MATERIAL, "source only code", "erp-b"
    ) is None
```

Add this typed-target round-trip after inserting a Ship, its Equipment, a
Material, and a Supplier:

```python
@pytest.mark.parametrize(
    ("entity_type", "entity_id", "raw_alias"),
    [
        (AliasEntityType.SUPPLIER, SUPPLIER_ID, "supplier alias"),
        (AliasEntityType.EQUIPMENT, EQUIPMENT_ID, "equipment alias"),
        (AliasEntityType.MATERIAL, MATERIAL_ID, "material alias"),
    ],
)
def test_alias_round_trip_preserves_typed_target(
    migrated_session: Session,
    entity_type: AliasEntityType,
    entity_id: UUID,
    raw_alias: str,
) -> None:
    from infra.postgres import AliasRepository, DomainRepository

    ship = _ship(SHIP_ID)
    domain_repository = DomainRepository(migrated_session)
    for entity in (
        ship,
        _equipment(EQUIPMENT_ID, ship.id),
        _material(MATERIAL_ID, "MAT-ROUNDTRIP"),
        _supplier(SUPPLIER_ID, "supplier-roundtrip", "SUP-ROUNDTRIP", "Supplier"),
    ):
        domain_repository.insert(entity)
    alias = EntityAlias(
        id=ALIAS_ID,
        entity_type=entity_type,
        entity_id=entity_id,
        alias=raw_alias,
    )
    repository = AliasRepository(migrated_session)
    repository.insert(alias)
    migrated_session.commit()

    loaded = repository.resolve(entity_type, raw_alias)
    assert loaded is not None
    assert loaded.entity_type is entity_type
    assert loaded.entity_id == entity_id
```

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_entity_alias_repository.py::test_three_explicit_supplier_aliases_resolve_to_one_canonical_supplier \
  tests/integration/test_entity_alias_repository.py::test_source_specific_alias_precedes_global_without_crossing_sources \
  -v
```

Expected: import fails because `AliasRepository` does not exist.

- [ ] **Step 3: Implement the repository**

Create `infra/postgres/alias_repository.py` with:

```python
"""Exact PostgreSQL persistence for explicit canonical entity aliases."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from infra.postgres.models import EntityAliasModel
from packages.domain import (
    AliasEntityType,
    DomainValidationError,
    EntityAlias,
    normalize_alias,
)


class AliasPersistenceError(RuntimeError):
    """Raised when an explicit alias violates persistence constraints."""


def _to_model(alias: EntityAlias) -> EntityAliasModel:
    return EntityAliasModel(
        id=alias.id,
        entity_type=alias.entity_type.value,
        alias=alias.alias,
        normalized_alias=alias.normalized_alias,
        source_system=alias.source_system,
        supplier_id=(
            alias.entity_id
            if alias.entity_type is AliasEntityType.SUPPLIER
            else None
        ),
        equipment_id=(
            alias.entity_id
            if alias.entity_type is AliasEntityType.EQUIPMENT
            else None
        ),
        material_id=(
            alias.entity_id
            if alias.entity_type is AliasEntityType.MATERIAL
            else None
        ),
    )


def _to_domain(model: EntityAliasModel) -> EntityAlias:
    try:
        entity_type = AliasEntityType(model.entity_type)
    except ValueError:
        raise AliasPersistenceError("stored entity alias is invalid") from None
    entity_id = {
        AliasEntityType.SUPPLIER: model.supplier_id,
        AliasEntityType.EQUIPMENT: model.equipment_id,
        AliasEntityType.MATERIAL: model.material_id,
    }[entity_type]
    if entity_id is None:
        raise AliasPersistenceError("stored entity alias is invalid")
    alias = EntityAlias(
        id=model.id,
        entity_type=entity_type,
        entity_id=entity_id,
        alias=model.alias,
        source_system=model.source_system,
    )
    if alias.normalized_alias != model.normalized_alias:
        raise AliasPersistenceError("stored entity alias is invalid")
    return alias


def _validated_source_system(value: str | None) -> str | None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise DomainValidationError(
            "source_system must be non-blank when provided"
        )
    return value


class AliasRepository:
    """Insert and exactly resolve aliases in a caller-owned Session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def insert(self, alias: EntityAlias) -> None:
        try:
            with self._session.begin_nested():
                self._session.add(_to_model(alias))
                self._session.flush()
        except IntegrityError:
            raise AliasPersistenceError(
                "entity alias violates persistence constraints"
            ) from None

    def resolve(
        self,
        entity_type: AliasEntityType,
        raw_alias: str,
        source_system: str | None = None,
    ) -> EntityAlias | None:
        normalized_alias = normalize_alias(raw_alias)
        source_system = _validated_source_system(source_system)
        base = select(EntityAliasModel).where(
            EntityAliasModel.entity_type == entity_type.value,
            EntityAliasModel.normalized_alias == normalized_alias,
        )
        if source_system is not None:
            source_match = self._session.scalar(
                base.where(EntityAliasModel.source_system == source_system)
            )
            if source_match is not None:
                return _to_domain(source_match)
        global_match = self._session.scalar(
            base.where(EntityAliasModel.source_system.is_(None))
        )
        return _to_domain(global_match) if global_match is not None else None
```

Export `AliasPersistenceError` and `AliasRepository` from
`infra/postgres/__init__.py`.

- [ ] **Step 4: Add failure, collision, and session-recovery tests**

Add the following fixed-error and session-recovery cases:

```python
def test_missing_target_uses_safe_error_and_preserves_session(
    migrated_session: Session,
) -> None:
    from infra.postgres import (
        AliasPersistenceError,
        AliasRepository,
        DomainRepository,
    )

    sensitive_alias = "missing-sensitive-alias"
    missing_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    repository = AliasRepository(migrated_session)
    missing = EntityAlias(
        id=ALIAS_ID,
        entity_type=AliasEntityType.SUPPLIER,
        entity_id=missing_id,
        alias=sensitive_alias,
    )
    with pytest.raises(AliasPersistenceError) as captured:
        repository.insert(missing)

    assert str(captured.value) == "entity alias violates persistence constraints"
    assert sensitive_alias not in str(captured.value)
    assert str(missing_id) not in str(captured.value)

    supplier = _supplier(SUPPLIER_ID, "supplier-recovery", "SUP-R", "Recovered")
    DomainRepository(migrated_session).insert(supplier)
    valid = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000006"),
        entity_type=AliasEntityType.SUPPLIER,
        entity_id=supplier.id,
        alias="valid-after-rejection",
    )
    repository.insert(valid)
    assert repository.resolve(AliasEntityType.SUPPLIER, valid.alias) == valid


def test_alias_collision_does_not_reassign_and_entity_types_are_independent(
    migrated_session: Session,
) -> None:
    from infra.postgres import (
        AliasPersistenceError,
        AliasRepository,
        DomainRepository,
    )

    supplier = _supplier(SUPPLIER_ID, "supplier-collision", "SUP-C", "Supplier")
    material = _material(MATERIAL_ID, "MAT-C")
    domain_repository = DomainRepository(migrated_session)
    domain_repository.insert(supplier)
    domain_repository.insert(material)
    repository = AliasRepository(migrated_session)
    first = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000007"),
        entity_type=AliasEntityType.SUPPLIER,
        entity_id=supplier.id,
        alias=" Shared  Code ",
    )
    duplicate = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000008"),
        entity_type=AliasEntityType.SUPPLIER,
        entity_id=supplier.id,
        alias="shared code",
    )
    material_alias = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000009"),
        entity_type=AliasEntityType.MATERIAL,
        entity_id=material.id,
        alias="shared code",
    )
    repository.insert(first)
    with pytest.raises(
        AliasPersistenceError,
        match="^entity alias violates persistence constraints$",
    ):
        repository.insert(duplicate)
    repository.insert(material_alias)

    assert repository.resolve(AliasEntityType.SUPPLIER, "shared code") == first
    assert repository.resolve(AliasEntityType.MATERIAL, "shared code") == material_alias


def test_source_specific_collision_is_rejected_only_within_exact_source(
    migrated_session: Session,
) -> None:
    from infra.postgres import (
        AliasPersistenceError,
        AliasRepository,
        DomainRepository,
    )

    supplier = _supplier(SUPPLIER_ID, "supplier-source", "SUP-S", "Supplier")
    DomainRepository(migrated_session).insert(supplier)
    repository = AliasRepository(migrated_session)
    first = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000011"),
        entity_type=AliasEntityType.SUPPLIER,
        entity_id=supplier.id,
        alias="Source code",
        source_system="erp-a",
    )
    duplicate_same_source = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000012"),
        entity_type=AliasEntityType.SUPPLIER,
        entity_id=supplier.id,
        alias=" source  code ",
        source_system="erp-a",
    )
    other_source = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000013"),
        entity_type=AliasEntityType.SUPPLIER,
        entity_id=supplier.id,
        alias="source code",
        source_system="erp-b",
    )
    repository.insert(first)
    with pytest.raises(
        AliasPersistenceError,
        match="^entity alias violates persistence constraints$",
    ):
        repository.insert(duplicate_same_source)
    repository.insert(other_source)

    assert repository.resolve(
        AliasEntityType.SUPPLIER, "source code", "erp-a"
    ) == first
    assert repository.resolve(
        AliasEntityType.SUPPLIER, "source code", "erp-b"
    ) == other_source


def test_database_rejects_entity_type_and_typed_target_mismatch(
    migrated_session: Session,
) -> None:
    from infra.postgres import DomainRepository
    from infra.postgres.models import EntityAliasModel

    ship = _ship(SHIP_ID)
    equipment = _equipment(EQUIPMENT_ID, ship.id)
    domain_repository = DomainRepository(migrated_session)
    domain_repository.insert(ship)
    domain_repository.insert(equipment)
    migrated_session.flush()

    with pytest.raises(IntegrityError), migrated_session.begin_nested():
        migrated_session.add(
            EntityAliasModel(
                id=ALIAS_ID,
                entity_type="supplier",
                alias="wrong target",
                normalized_alias="wrong target",
                source_system=None,
                supplier_id=None,
                equipment_id=equipment.id,
                material_id=None,
            )
        )
        migrated_session.flush()


def test_resolve_rejects_blank_source_system_without_value_leak(
    migrated_session: Session,
) -> None:
    from infra.postgres import AliasRepository
    from packages.domain import DomainValidationError

    with pytest.raises(DomainValidationError) as captured:
        AliasRepository(migrated_session).resolve(
            AliasEntityType.SUPPLIER,
            "safe alias",
            "   ",
        )

    assert str(captured.value) == "source_system must be non-blank when provided"
```

- [ ] **Step 5: Run repository GREEN and static checks**

```bash
TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_entity_alias_repository.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  infra/postgres packages/domain tests/integration/test_entity_alias_repository.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  infra/postgres packages/domain tests/integration/test_entity_alias_repository.py
```

Expected: all alias repository cases pass; Ruff and mypy pass.

- [ ] **Step 6: Commit the repository slice**

```bash
git add infra/postgres/alias_repository.py infra/postgres/__init__.py \
  tests/integration/test_entity_alias_repository.py
git commit -m "feat: add exact entity alias repository"
```

---

### Task 4: Scope-Safe Entity Resolution Service

**Files:**
- Create: `services/entity_resolution/__init__.py`
- Create: `services/entity_resolution/service.py`
- Modify: `tests/unit/test_entity_aliases.py`
- Create: `tests/security/test_entity_alias_scope.py`

**Interfaces:**
- Consumes: domain aliases, `UserContext`, `AuthorizationScope`, `authorization_scope_for`, an alias-reader protocol, and `Callable[[UUID], Equipment | None]`.
- Produces: `EntityResolutionService.resolve(...) -> EntityAlias | None` with service-layer authorization.

- [ ] **Step 1: Add failing global-master-data and no-fuzzy service tests**

Append a deterministic fake reader to `tests/unit/test_entity_aliases.py`
(extend its domain imports with `AliasEntityType`, `EntityAlias`, and
`normalize_alias`):

```python
class _FakeAliasReader:
    def __init__(self, aliases: list[EntityAlias]) -> None:
        self.aliases = aliases
        self.calls: list[tuple[AliasEntityType, str, str | None]] = []

    def resolve(
        self,
        entity_type: AliasEntityType,
        raw_alias: str,
        source_system: str | None = None,
    ) -> EntityAlias | None:
        self.calls.append((entity_type, raw_alias, source_system))
        key = normalize_alias(raw_alias)
        source_matches = [
            alias
            for alias in self.aliases
            if alias.entity_type is entity_type
            and alias.normalized_alias == key
            and alias.source_system == source_system
        ]
        if source_system is not None and source_matches:
            return source_matches[0]
        return next(
            (
                alias
                for alias in self.aliases
                if alias.entity_type is entity_type
                and alias.normalized_alias == key
                and alias.source_system is None
            ),
            None,
        )
```

Add these global-master-data and no-fuzzy tests:

```python
@pytest.mark.parametrize(
    "entity_type",
    [AliasEntityType.SUPPLIER, AliasEntityType.MATERIAL],
)
def test_global_master_alias_resolves_for_authenticated_user(
    entity_type: AliasEntityType,
) -> None:
    from packages.contracts.auth import UserContext
    from services.entity_resolution import EntityResolutionService

    alias = EntityAlias(
        id=ALIAS_ID,
        entity_type=entity_type,
        entity_id=SUPPLIER_ID,
        alias="explicit alias",
    )
    reader = _FakeAliasReader([alias])
    service = EntityResolutionService(reader, lambda _: None)

    assert service.resolve(
        entity_type=entity_type,
        raw_alias="EXPLICIT ALIAS",
        user_context=UserContext(user_id="authenticated-user"),
    ) == alias


def test_resolution_does_not_create_or_suggest_fuzzy_aliases() -> None:
    from packages.contracts.auth import UserContext
    from services.entity_resolution import EntityResolutionService

    explicit = EntityAlias(
        id=ALIAS_ID,
        entity_type=AliasEntityType.SUPPLIER,
        entity_id=SUPPLIER_ID,
        alias="Wartsila",
    )
    reader = _FakeAliasReader([explicit])
    service = EntityResolutionService(reader, lambda _: None)

    assert service.resolve(
        entity_type=AliasEntityType.SUPPLIER,
        raw_alias="Wartsilla",
        user_context=UserContext(user_id="authenticated-user"),
    ) is None
    assert reader.aliases == [explicit]
    assert reader.calls == [
        (AliasEntityType.SUPPLIER, "Wartsilla", None)
    ]
```

- [ ] **Step 2: Add failing Equipment scope security tests**

Create `tests/security/test_entity_alias_scope.py` with these complete imports
and helpers for one Equipment alias on ship A:

```python
from datetime import UTC, datetime
from uuid import UUID

import pytest

from packages.contracts.auth import AuthorizationScope, UserContext
from packages.domain import AliasEntityType, EntityAlias, Equipment, normalize_alias
from services.entity_resolution import EntityResolutionService

SHIP_ID = UUID("73000000-0000-0000-0000-000000000001")
EQUIPMENT_ID = UUID("73000000-0000-0000-0000-000000000002")
ALIAS_ID = UUID("73000000-0000-0000-0000-000000000003")


class _Reader:
    def __init__(self, alias: EntityAlias) -> None:
        self.alias = alias

    def resolve(
        self,
        entity_type: AliasEntityType,
        raw_alias: str,
        source_system: str | None = None,
    ) -> EntityAlias | None:
        if (
            entity_type is self.alias.entity_type
            and normalize_alias(raw_alias) == self.alias.normalized_alias
            and source_system == self.alias.source_system
        ):
            return self.alias
        return None


def _service_fixture() -> tuple[
    EntityResolutionService,
    EntityAlias,
    Equipment,
]:
    equipment = Equipment(
        id=EQUIPMENT_ID,
        source_system="synthetic-source",
        source_id="equipment-scope",
        source_updated_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
        ship_id=SHIP_ID,
        equipment_code="EQ-SCOPE",
    )
    alias = EntityAlias(
        id=ALIAS_ID,
        entity_type=AliasEntityType.EQUIPMENT,
        entity_id=equipment.id,
        alias="Main Cooling Pump",
    )
    return (
        EntityResolutionService(
            _Reader(alias),
            lambda entity_id: equipment if entity_id == equipment.id else None,
        ),
        alias,
        equipment,
    )
```

Add these tests below the helpers:

```python
def test_equipment_alias_resolves_inside_allowed_ship_scope() -> None:
    service, alias, equipment = _service_fixture()
    context = UserContext(
        user_id="allowed-user",
        allowed_ship_ids={str(equipment.ship_id)},
    )

    assert service.resolve(
        entity_type=AliasEntityType.EQUIPMENT,
        raw_alias=alias.alias,
        user_context=context,
    ) == alias


@pytest.mark.parametrize(
    "allowed_ship_ids",
    [set(), {"72000000-0000-0000-0000-ffffffffffff"}],
)
def test_equipment_alias_does_not_leak_across_ship_scope(
    allowed_ship_ids: set[str],
) -> None:
    service, alias, _ = _service_fixture()
    context = UserContext(
        user_id="out-of-scope-user",
        allowed_ship_ids=allowed_ship_ids,
    )

    assert service.resolve(
        entity_type=AliasEntityType.EQUIPMENT,
        raw_alias=alias.alias,
        user_context=context,
    ) is None


def test_requested_scope_can_narrow_but_not_widen_equipment_access() -> None:
    service, alias, equipment = _service_fixture()
    context = UserContext(
        user_id="authenticated-user",
        allowed_ship_ids={str(equipment.ship_id)},
    )
    narrowed = AuthorizationScope(allowed_ship_ids=set())

    assert service.resolve(
        entity_type=AliasEntityType.EQUIPMENT,
        raw_alias=alias.alias,
        user_context=context,
        requested_scope=narrowed,
    ) is None
```

Add the missing-canonical case below; together with
`test_equipment_alias_does_not_leak_across_ship_scope`, both observable
results are exactly `None`:

```python
def test_missing_canonical_equipment_is_indistinguishable_from_denial() -> None:
    _, alias, equipment = _service_fixture()
    service = EntityResolutionService(_Reader(alias), lambda _: None)
    context = UserContext(
        user_id="allowed-user",
        allowed_ship_ids={str(equipment.ship_id)},
    )

    assert service.resolve(
        entity_type=AliasEntityType.EQUIPMENT,
        raw_alias=alias.alias,
        user_context=context,
    ) is None
```

- [ ] **Step 3: Run service/security tests and confirm RED**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/test_entity_aliases.py tests/security/test_entity_alias_scope.py -v
```

Expected: imports fail because `services.entity_resolution` is absent.

- [ ] **Step 4: Implement the service behind a protocol**

Create `services/entity_resolution/service.py`:

```python
"""Authorization-aware exact resolution of canonical entity aliases."""

from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from packages.contracts.auth import AuthorizationScope, UserContext
from packages.domain import AliasEntityType, EntityAlias, Equipment
from services.auth.service import authorization_scope_for


class AliasReader(Protocol):
    """Port required for exact alias lookup."""

    def resolve(
        self,
        entity_type: AliasEntityType,
        raw_alias: str,
        source_system: str | None = None,
    ) -> EntityAlias | None: ...


class EntityResolutionService:
    """Resolve aliases without exposing out-of-scope Equipment existence."""

    def __init__(
        self,
        alias_reader: AliasReader,
        equipment_by_id: Callable[[UUID], Equipment | None],
    ) -> None:
        self._alias_reader = alias_reader
        self._equipment_by_id = equipment_by_id

    def resolve(
        self,
        *,
        entity_type: AliasEntityType,
        raw_alias: str,
        user_context: UserContext,
        source_system: str | None = None,
        requested_scope: AuthorizationScope | None = None,
    ) -> EntityAlias | None:
        scope = authorization_scope_for(user_context, requested_scope)
        if (
            entity_type is AliasEntityType.EQUIPMENT
            and not scope.allowed_ship_ids
        ):
            return None
        alias = self._alias_reader.resolve(
            entity_type,
            raw_alias,
            source_system,
        )
        if alias is None:
            return None
        if entity_type is not AliasEntityType.EQUIPMENT:
            return alias
        equipment = self._equipment_by_id(alias.entity_id)
        if equipment is None:
            return None
        if str(equipment.ship_id) not in scope.allowed_ship_ids:
            return None
        return alias
```

Create `services/entity_resolution/__init__.py` with:

```python
"""Authorization-aware canonical entity resolution."""

from services.entity_resolution.service import (
    AliasReader,
    EntityResolutionService,
)

__all__ = ["AliasReader", "EntityResolutionService"]
```

- [ ] **Step 5: Run GREEN, relevant authorization tests, Ruff, and mypy**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/test_entity_aliases.py \
  tests/security/test_entity_alias_scope.py \
  tests/unit/test_authorization_scope.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  packages/domain services/entity_resolution tests/unit/test_entity_aliases.py \
  tests/security/test_entity_alias_scope.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  packages/domain services/entity_resolution tests/unit/test_entity_aliases.py \
  tests/security/test_entity_alias_scope.py
```

Expected: all focused tests, Ruff, and mypy pass.

- [ ] **Step 6: Commit the authorization service slice**

```bash
git add services/entity_resolution/__init__.py \
  services/entity_resolution/service.py tests/unit/test_entity_aliases.py \
  tests/security/test_entity_alias_scope.py
git commit -m "feat: add scope-safe entity resolution"
```

---

### Task 5: Runtime Contract, Operator Documentation, and Final Gate

**Files:**
- Modify: `tests/integration/test_deployment.py`
- Modify: `infra/postgres/README.md`
- Modify: `docs/02-domain-model.md`

**Interfaces:**
- Consumes: completed domain, repository, service, and migration public contracts.
- Produces: installed-artifact smoke coverage and operator-facing alias semantics.

- [ ] **Step 1: Write a failing documentation contract test**

Add to `tests/integration/test_deployment.py`:

```python
def test_postgres_operator_docs_cover_entity_alias_safety() -> None:
    documentation = REPOSITORY_ROOT.joinpath("infra/postgres/README.md").read_text(
        encoding="utf-8"
    )

    assert "20260818_0002" in documentation
    assert "Wärtsilä" in documentation
    assert "Wartsila" in documentation
    assert "瓦锡兰" in documentation
    assert "No fuzzy" in documentation
    assert "source-specific" in documentation
    assert "caller-owned" in documentation
```

Run the test and confirm it fails on missing Task 007 documentation.

- [ ] **Step 2: Expand installed-artifact smoke coverage**

Modify the isolated `-S` smoke command to contain these imports and printed
names:

```python
"from infra.postgres import AliasRepository, Base, DomainRepository; "
"from packages.domain import EntityAlias; "
"from services.entity_resolution import EntityResolutionService; "
"print(REDACTED, AuthorizationScope.__name__, "
"LocalAuthenticationAdapter.__name__, authorization_scope_for.__name__, "
"Base.__name__, DomainRepository.__name__, AliasRepository.__name__, "
"EntityAlias.__name__, EntityResolutionService.__name__)"
```

Replace the exact expected stdout with:

```python
assert smoke.stdout.strip() == (
    "[REDACTED] AuthorizationScope LocalAuthenticationAdapter "
    "authorization_scope_for Base DomainRepository AliasRepository "
    "EntityAlias EntityResolutionService"
)
```

Run the deployment artifact test; it must pass without the source checkout on
`PYTHONPATH`.

- [ ] **Step 3: Document exact operator and domain behavior**

Append this section to `infra/postgres/README.md`:

````markdown
## Entity aliases

Migration `20260818_0002` (parent `20260817_0001`) creates
`entity_aliases` for Supplier, Equipment, and Material. Each row has exactly
one typed foreign key. Register `Wärtsilä`, `Wartsila`, and `瓦锡兰` as three
explicit rows when all three names refer to one canonical Supplier.

Normalization applies Unicode NFKC, case folding, and whitespace collapse.
It preserves accents and punctuation. No fuzzy matching, transliteration,
candidate generation, or automatic merge occurs.

Global aliases have no `source_system`. A source-specific lookup first checks
the exact requested source and then falls back to the global alias; a lookup
without a source checks only the global alias. The repository uses a
caller-owned Session and transaction and returns fixed persistence errors
without rejected values. Equipment resolution is additionally limited by the
service's server-derived ship scope.

Run the synthetic PostgreSQL tests only against the protected database:

```bash
TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
  python -m pytest tests/integration/test_entity_alias_repository.py -v
```
````

Replace the Example paragraph in `docs/02-domain-model.md` with:

```markdown
Aliases are explicit links; they never replace canonical UUIDs.
`Wärtsilä`, `Wartsila`, and `瓦锡兰` require three stored aliases to resolve
to one Supplier. Normalization applies NFKC, case folding, and whitespace
collapse while preserving accents and punctuation. No fuzzy lookup or
automatic merge is allowed. A source-specific exact match precedes a global
fallback; a lookup without a source sees only global aliases. Supplier and
Material aliases are authenticated global master data. Equipment aliases
resolve only when the canonical Equipment belongs to the server-derived
allowed ship scope; missing and unauthorized Equipment both return no result.
```

Do not document an API or Task 008 fixture.

- [ ] **Step 4: Run documentation GREEN and deployment smoke**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_deployment.py -v
```

Expected: documentation contract and installed-artifact imports pass.

- [ ] **Step 5: Run the fresh Task 007 final gate**

```bash
TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_domain_repository.py \
  tests/integration/test_entity_alias_repository.py -v
TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
make check PYTHON=/Users/wuhao/Documents/shipyard-ai/.venv/bin/python
DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m alembic upgrade head
DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m alembic check
DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m alembic upgrade head --sql
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check .
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy .
git diff --check main...HEAD
```

Require:

- all unit, integration, and security tests pass;
- PostgreSQL tests do not skip with the supplied URL;
- Alembic reports head `20260818_0002` with no metadata drift;
- offline SQL includes `CREATE TABLE entity_aliases` and both partial unique
  indexes;
- Ruff and mypy pass;
- installed artifact imports all Task 007 public contracts;
- no `EntityAlias` behavior appears in Task 008 or Agent/API packages; and
- no real data, credentials, fuzzy matcher, or model dependency is introduced.

- [ ] **Step 6: Commit documentation and deployment coverage**

```bash
git add tests/integration/test_deployment.py infra/postgres/README.md \
  docs/02-domain-model.md
git commit -m "docs: document explicit entity aliases"
```

- [ ] **Step 7: Request whole-branch review**

Review `main...HEAD` against `AGENTS.md`, `tasks/007-entity-aliases.md`, and the
design spec. Fix every P0/P1/P2 finding, re-run the complete final gate after
the last fix, and stop without beginning Task 008.
