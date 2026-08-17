# Task 004 Authentication Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add immutable server-side identity and authorization-scope contracts, monotonic scope narrowing, and a safe local-development authentication adapter.

**Architecture:** Transport-independent Pydantic contracts represent authenticated identity and authorization scope. A pure service derives and narrows scopes, while a development-only in-memory adapter resolves opaque credentials to server-registered contexts without accepting caller-provided identity claims.

**Tech Stack:** Python 3.12+, Pydantic 2.x, pytest 8.x, Ruff 0.9.x, mypy 1.14.x, setuptools 75.x.

## Global Constraints

- Implement only `tasks/004-auth-context.md`; do not begin Task 005.
- Authentication and authorization are separate; authorization is enforced server-side and defaults to deny.
- `UserContext` comes from a trusted host adapter and remains separate from model/tool business arguments.
- Contracts, services, and adapters must not depend on FastAPI, PostgreSQL, an LLM SDK, external IdP, network, filesystem, or customer data.
- Security levels are ordered `PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED`.
- Set-valued authorization dimensions are immutable and scope intersection cannot broaden permissions.
- Missing and unknown local credentials produce the same credential-free error.
- Every behavior change follows failing test, confirmed RED, minimal implementation, focused GREEN, relevant suite, Ruff, and mypy.
- Tests use synthetic values and make no network or external model calls.

## File Structure

- `packages/contracts/auth.py`: ordered security level and immutable public `UserContext`/`AuthorizationScope` contracts.
- `packages/contracts/__init__.py`: explicit public exports for authentication contracts.
- `services/auth/service.py`: pure derivation and monotonic narrowing of authorization scopes.
- `services/auth/__init__.py`: public authorization-service export.
- `services/__init__.py`: top-level service package marker.
- `adapters/auth/local.py`: generic-error local credential registry adapter.
- `adapters/auth/__init__.py`: public local-authentication exports.
- `adapters/__init__.py`: top-level adapter package marker.
- `tests/unit/test_authorization_scope.py`: contract, service, adapter, edge, and security behavior.
- `tests/integration/test_deployment.py`: installed Docker build artifact imports the new runtime packages from an isolated directory.
- `pyproject.toml`: package discovery includes `services*` and `adapters*`.
- `Dockerfile`: Docker build context copies the new runtime package trees.
- `docs/05-tool-contracts.md`: public identity/scope contract and host-injection rule.
- `docs/06-security.md`: ordered clearance and scope-intersection semantics.

---

### Task 1: Immutable Authentication and Authorization Contracts

**Files:**
- Create: `packages/contracts/__init__.py`
- Create: `packages/contracts/auth.py`
- Create: `tests/unit/test_authorization_scope.py`

**Interfaces:**
- Consumes: Pydantic `BaseModel`, `ConfigDict`, and `StringConstraints`.
- Produces: `SecurityLevel`, `UserContext`, `AuthorizationScope`, and `AuthorizationScope.intersection(other: AuthorizationScope) -> AuthorizationScope`.

- [ ] **Step 1: Write the first failing contract tests**

Create `tests/unit/test_authorization_scope.py` with the primary default-deny and full-intersection behaviors:

```python
from typing import Any, cast

import pytest
from pydantic import ValidationError


def test_authorization_scope_defaults_to_deny_all_scoped_dimensions() -> None:
    from packages.contracts.auth import AuthorizationScope, SecurityLevel

    scope = AuthorizationScope()

    assert scope.roles == frozenset()
    assert scope.departments == frozenset()
    assert scope.allowed_ship_ids == frozenset()
    assert scope.allowed_project_ids == frozenset()
    assert scope.security_level is SecurityLevel.PUBLIC


def test_scope_intersection_narrows_every_dimension_and_clearance() -> None:
    from packages.contracts.auth import AuthorizationScope, SecurityLevel

    authenticated = AuthorizationScope(
        roles={"project_manager", "engineer"},
        departments={"design", "production"},
        allowed_ship_ids={"ship-001", "ship-002"},
        allowed_project_ids={"project-001", "project-002"},
        security_level=SecurityLevel.CONFIDENTIAL,
    )
    requested = AuthorizationScope(
        roles={"project_manager", "procurement"},
        departments={"production", "quality"},
        allowed_ship_ids={"ship-002", "ship-003"},
        allowed_project_ids={"project-002", "project-003"},
        security_level=SecurityLevel.RESTRICTED,
    )

    result = authenticated.intersection(requested)

    assert result == AuthorizationScope(
        roles={"project_manager"},
        departments={"production"},
        allowed_ship_ids={"ship-002"},
        allowed_project_ids={"project-002"},
        security_level=SecurityLevel.CONFIDENTIAL,
    )


def test_disjoint_scope_intersection_stays_empty() -> None:
    from packages.contracts.auth import AuthorizationScope, SecurityLevel

    result = AuthorizationScope(
        roles={"engineering"},
        departments={"design"},
        allowed_ship_ids={"ship-001"},
        allowed_project_ids={"project-001"},
        security_level=SecurityLevel.INTERNAL,
    ).intersection(
        AuthorizationScope(
            roles={"procurement"},
            departments={"supply"},
            allowed_ship_ids={"ship-002"},
            allowed_project_ids={"project-002"},
            security_level=SecurityLevel.PUBLIC,
        )
    )

    assert result == AuthorizationScope(security_level=SecurityLevel.PUBLIC)


def test_auth_contracts_are_immutable_and_reject_unknown_fields() -> None:
    from packages.contracts.auth import AuthorizationScope, SecurityLevel, UserContext

    scope = AuthorizationScope(roles={"engineering"})
    context = UserContext(user_id="user-001", roles={"engineering"})

    assert isinstance(scope.roles, frozenset)
    assert isinstance(context.roles, frozenset)
    with pytest.raises(ValidationError):
        cast(Any, scope).security_level = SecurityLevel.RESTRICTED
    with pytest.raises(ValidationError):
        cast(Any, context).user_id = "attacker"
    with pytest.raises(ValidationError):
        AuthorizationScope.model_validate(
            {"roles": ["engineering"], "user_id": "attacker"}
        )
    with pytest.raises(ValidationError):
        UserContext.model_validate(
            {"user_id": "user-001", "model_supplied_role": "admin"}
        )
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/test_authorization_scope.py -v
```

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'packages.contracts'`.

- [ ] **Step 3: Implement the minimum immutable contracts**

Create `packages/contracts/auth.py`:

```python
"""Transport-independent authentication and authorization contracts."""

from enum import IntEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

type Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SecurityLevel(IntEnum):
    """Ordered information-security levels from least to most privileged."""

    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class UserContext(_FrozenContract):
    """Identity claims already authenticated by a trusted host adapter."""

    user_id: Identifier
    roles: frozenset[Identifier] = Field(default_factory=frozenset)
    departments: frozenset[Identifier] = Field(default_factory=frozenset)
    allowed_ship_ids: frozenset[Identifier] = Field(default_factory=frozenset)
    allowed_project_ids: frozenset[Identifier] = Field(default_factory=frozenset)
    security_clearance: SecurityLevel = SecurityLevel.PUBLIC


class AuthorizationScope(_FrozenContract):
    """Server-derived permissions; the default contains no scoped access."""

    roles: frozenset[Identifier] = Field(default_factory=frozenset)
    departments: frozenset[Identifier] = Field(default_factory=frozenset)
    allowed_ship_ids: frozenset[Identifier] = Field(default_factory=frozenset)
    allowed_project_ids: frozenset[Identifier] = Field(default_factory=frozenset)
    security_level: SecurityLevel = SecurityLevel.PUBLIC

    def intersection(self, other: Self) -> Self:
        """Return a scope no broader than either input scope."""
        return type(self)(
            roles=self.roles & other.roles,
            departments=self.departments & other.departments,
            allowed_ship_ids=self.allowed_ship_ids & other.allowed_ship_ids,
            allowed_project_ids=(
                self.allowed_project_ids & other.allowed_project_ids
            ),
            security_level=min(self.security_level, other.security_level),
        )
```

Create `packages/contracts/__init__.py`:

```python
"""Public transport-independent contracts."""

from packages.contracts.auth import AuthorizationScope, SecurityLevel, UserContext

__all__ = ["AuthorizationScope", "SecurityLevel", "UserContext"]
```

- [ ] **Step 4: Run the focused tests and confirm GREEN**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/test_authorization_scope.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run contract lint and type checks**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check packages/contracts tests/unit/test_authorization_scope.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy packages/contracts tests/unit/test_authorization_scope.py
```

Expected: Ruff reports `All checks passed!`; mypy reports no issues.

- [ ] **Step 6: Commit the contract behavior**

```bash
git add packages/contracts tests/unit/test_authorization_scope.py
git commit -m "feat: add immutable authorization contracts"
```

---

### Task 2: Server-Side Scope Derivation and Narrowing

**Files:**
- Create: `services/__init__.py`
- Create: `services/auth/__init__.py`
- Create: `services/auth/service.py`
- Modify: `tests/unit/test_authorization_scope.py`

**Interfaces:**
- Consumes: `UserContext`, `AuthorizationScope`.
- Produces: `authorization_scope_for(user_context: UserContext, requested_scope: AuthorizationScope | None = None) -> AuthorizationScope`.

- [ ] **Step 1: Append failing service tests**

Append:

```python
def test_authorization_service_derives_scope_from_authenticated_context() -> None:
    from packages.contracts.auth import AuthorizationScope, SecurityLevel, UserContext
    from services.auth.service import authorization_scope_for

    user = UserContext(
        user_id="user-001",
        roles={"engineering"},
        departments={"design"},
        allowed_ship_ids={"ship-001"},
        allowed_project_ids={"project-001"},
        security_clearance=SecurityLevel.CONFIDENTIAL,
    )

    assert authorization_scope_for(user) == AuthorizationScope(
        roles={"engineering"},
        departments={"design"},
        allowed_ship_ids={"ship-001"},
        allowed_project_ids={"project-001"},
        security_level=SecurityLevel.CONFIDENTIAL,
    )


def test_requested_scope_cannot_expand_authenticated_permissions() -> None:
    from packages.contracts.auth import AuthorizationScope, SecurityLevel, UserContext
    from services.auth.service import authorization_scope_for

    user = UserContext(
        user_id="user-001",
        roles={"engineering"},
        departments={"design"},
        allowed_ship_ids={"ship-001"},
        allowed_project_ids={"project-001"},
        security_clearance=SecurityLevel.INTERNAL,
    )
    requested = AuthorizationScope(
        roles={"engineering", "admin"},
        departments={"design", "executive"},
        allowed_ship_ids={"ship-001", "ship-999"},
        allowed_project_ids={"project-001", "project-999"},
        security_level=SecurityLevel.RESTRICTED,
    )

    result = authorization_scope_for(user, requested)

    assert result == AuthorizationScope(
        roles={"engineering"},
        departments={"design"},
        allowed_ship_ids={"ship-001"},
        allowed_project_ids={"project-001"},
        security_level=SecurityLevel.INTERNAL,
    )
```

- [ ] **Step 2: Run the service tests and confirm RED**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/test_authorization_scope.py::test_authorization_service_derives_scope_from_authenticated_context tests/unit/test_authorization_scope.py::test_requested_scope_cannot_expand_authenticated_permissions -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'services.auth'`.

- [ ] **Step 3: Implement pure server-side scope derivation**

Create `services/__init__.py`:

```python
"""Application services."""
```

Create `services/auth/service.py`:

```python
"""Server-side authorization scope derivation."""

from packages.contracts.auth import AuthorizationScope, UserContext


def authorization_scope_for(
    user_context: UserContext,
    requested_scope: AuthorizationScope | None = None,
) -> AuthorizationScope:
    """Derive trusted permissions and optionally narrow them."""
    authenticated_scope = AuthorizationScope(
        roles=user_context.roles,
        departments=user_context.departments,
        allowed_ship_ids=user_context.allowed_ship_ids,
        allowed_project_ids=user_context.allowed_project_ids,
        security_level=user_context.security_clearance,
    )
    if requested_scope is None:
        return authenticated_scope
    return authenticated_scope.intersection(requested_scope)
```

Create `services/auth/__init__.py`:

```python
"""Authentication and authorization services."""

from services.auth.service import authorization_scope_for

__all__ = ["authorization_scope_for"]
```

- [ ] **Step 4: Run all Task 004 tests and confirm GREEN**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/test_authorization_scope.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Run service lint and type checks**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check services tests/unit/test_authorization_scope.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy services tests/unit/test_authorization_scope.py
```

Expected: Ruff and mypy pass.

- [ ] **Step 6: Commit the authorization service**

```bash
git add services tests/unit/test_authorization_scope.py
git commit -m "feat: derive and narrow authorization scopes"
```

---

### Task 3: Local Development Authentication Adapter

**Files:**
- Create: `adapters/__init__.py`
- Create: `adapters/auth/__init__.py`
- Create: `adapters/auth/local.py`
- Modify: `tests/unit/test_authorization_scope.py`

**Interfaces:**
- Consumes: a server-owned `Mapping[str, UserContext]` and `str | None` credential.
- Produces: `AuthenticationError` and `LocalAuthenticationAdapter.authenticate(credential: str | None) -> UserContext`.

- [ ] **Step 1: Append failing local-adapter and identity-boundary tests**

Append:

```python
def test_local_adapter_resolves_only_server_registered_identity() -> None:
    from adapters.auth.local import LocalAuthenticationAdapter
    from packages.contracts.auth import SecurityLevel, UserContext

    registered = UserContext(
        user_id="user-001",
        roles={"engineering"},
        departments={"design"},
        allowed_ship_ids={"ship-001"},
        allowed_project_ids={"project-001"},
        security_clearance=SecurityLevel.INTERNAL,
    )
    identities = {"dev-credential": registered}
    adapter = LocalAuthenticationAdapter(identities)
    identities["dev-credential"] = UserContext(user_id="attacker")

    assert adapter.authenticate("dev-credential") is registered


def test_local_adapter_rejects_model_style_identity_payload() -> None:
    from adapters.auth.local import AuthenticationError, LocalAuthenticationAdapter
    from packages.contracts.auth import UserContext

    adapter = LocalAuthenticationAdapter(
        {"dev-credential": UserContext(user_id="server-user")}
    )
    model_arguments = {
        "credential": "dev-credential",
        "user_id": "attacker",
        "roles": ["admin"],
    }

    with pytest.raises(AuthenticationError, match="^Authentication failed$"):
        adapter.authenticate(cast(Any, model_arguments))


@pytest.mark.parametrize("credential", [None, "", "unknown-sensitive-value"])
def test_local_adapter_fails_without_disclosing_credentials(
    credential: str | None,
) -> None:
    from adapters.auth.local import AuthenticationError, LocalAuthenticationAdapter

    adapter = LocalAuthenticationAdapter({})

    with pytest.raises(AuthenticationError) as captured:
        adapter.authenticate(credential)

    assert str(captured.value) == "Authentication failed"
    assert "unknown-sensitive-value" not in str(captured.value)
```

- [ ] **Step 2: Run the adapter tests and confirm RED**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/test_authorization_scope.py::test_local_adapter_resolves_only_server_registered_identity tests/unit/test_authorization_scope.py::test_local_adapter_rejects_model_style_identity_payload tests/unit/test_authorization_scope.py::test_local_adapter_fails_without_disclosing_credentials -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'adapters.auth'`.

- [ ] **Step 3: Implement the minimum safe local adapter**

Create `adapters/__init__.py`:

```python
"""Infrastructure and source-system adapters."""
```

Create `adapters/auth/local.py`:

```python
"""Development-only authentication backed by a server-owned registry."""

from collections.abc import Mapping

from packages.contracts.auth import UserContext


class AuthenticationError(RuntimeError):
    """Raised when a local credential cannot be authenticated."""


class LocalAuthenticationAdapter:
    """Resolve opaque local credentials without accepting identity claims."""

    def __init__(self, identities: Mapping[str, UserContext]) -> None:
        self._identities = dict(identities)

    def authenticate(self, credential: str | None) -> UserContext:
        if not isinstance(credential, str) or not credential:
            raise AuthenticationError("Authentication failed")
        context = self._identities.get(credential)
        if context is None:
            raise AuthenticationError("Authentication failed")
        return context
```

Create `adapters/auth/__init__.py`:

```python
"""Authentication adapter implementations."""

from adapters.auth.local import AuthenticationError, LocalAuthenticationAdapter

__all__ = ["AuthenticationError", "LocalAuthenticationAdapter"]
```

- [ ] **Step 4: Run all Task 004 tests and confirm GREEN**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/test_authorization_scope.py -v
```

Expected: 11 passed because the parameterized credential test creates three cases.

- [ ] **Step 5: Run adapter lint and type checks**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check adapters tests/unit/test_authorization_scope.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy adapters tests/unit/test_authorization_scope.py
```

Expected: Ruff and mypy pass.

- [ ] **Step 6: Commit the local adapter**

```bash
git add adapters tests/unit/test_authorization_scope.py
git commit -m "feat: add local authentication adapter"
```

---

### Task 4: Package and Deploy the New Runtime Boundaries

**Files:**
- Modify: `pyproject.toml`
- Modify: `Dockerfile`
- Modify: `tests/integration/test_deployment.py`

**Interfaces:**
- Consumes: the package imports created in Tasks 1-3.
- Produces: an installed artifact containing `packages.contracts`, `services.auth`, and `adapters.auth` inside the Docker build context.

- [ ] **Step 1: Strengthen the deployment packaging test first**

Rename `test_docker_build_inputs_install_common_package_artifact` to
`test_docker_build_inputs_install_runtime_package_artifact` and replace its
isolated smoke setup and command with the following. Add `import site` beside
the other standard-library imports so the isolated interpreter can load runtime
dependencies without processing editable-install `.pth` files:

```python
environment = os.environ.copy()
environment["PYTHONPATH"] = os.pathsep.join(
    [str(install_target), *site.getsitepackages()]
)
smoke = subprocess.run(
    [
        sys.executable,
        "-S",
        "-c",
        "from adapters.auth.local import LocalAuthenticationAdapter; "
        "from packages.common.logging import REDACTED; "
        "from packages.contracts.auth import AuthorizationScope; "
        "from services.auth.service import authorization_scope_for; "
        "print(REDACTED, AuthorizationScope.__name__, "
        "LocalAuthenticationAdapter.__name__, authorization_scope_for.__name__)",
    ],
    cwd=isolated_cwd,
    env=environment,
    capture_output=True,
    check=False,
    text=True,
)

assert smoke.returncode == 0, smoke.stdout + smoke.stderr
assert smoke.stdout.strip() == (
    "[REDACTED] AuthorizationScope LocalAuthenticationAdapter "
    "authorization_scope_for"
)
```

- [ ] **Step 2: Run the deployment test and confirm RED**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_deployment.py::test_docker_build_inputs_install_runtime_package_artifact -v
```

Expected: FAIL because the staged Docker context and installed artifact do not contain `adapters` or `services`.

- [ ] **Step 3: Add package discovery and Docker copy inputs**

Change `pyproject.toml` package discovery to:

```toml
[tool.setuptools.packages.find]
include = ["adapters*", "apps*", "packages*", "services*"]
```

Add to `Dockerfile` after the existing package copies:

```dockerfile
COPY adapters ./adapters
COPY services ./services
```

- [ ] **Step 4: Run the focused deployment test and confirm GREEN**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_deployment.py::test_docker_build_inputs_install_runtime_package_artifact -v
```

Expected: 1 passed.

- [ ] **Step 5: Run the complete deployment integration module**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_deployment.py -v
```

Expected: all deployment tests pass.

- [ ] **Step 6: Commit deployment packaging**

```bash
git add pyproject.toml Dockerfile tests/integration/test_deployment.py
git commit -m "build: package authentication boundaries"
```

---

### Task 5: Document the Public Contract and Verify Task 004

**Files:**
- Modify: `docs/05-tool-contracts.md`
- Modify: `docs/06-security.md`
- Verify: all Task 004 implementation and test files.

**Interfaces:**
- Consumes: final public names and behavior from Tasks 1-4.
- Produces: documented host-injection, default-deny, ordered-clearance, and intersection semantics.

- [ ] **Step 1: Document the exact public identity contract**

Update the common-types section of `docs/05-tool-contracts.md` to state:

```text
UserContext is an immutable, already-authenticated server-side value. The host
injects it through a parameter separate from model-generated tool arguments.
Tool schemas must not expose user_id, roles, departments, allowed_ship_ids,
allowed_project_ids, or security_clearance as identity overrides.

AuthorizationScope
- roles[]
- departments[]
- allowed_ship_ids[]
- allowed_project_ids[]
- security_level
```

- [ ] **Step 2: Document authorization ordering and intersection**

Update `docs/06-security.md` to state:

```text
Security levels are ordered PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED.
The default AuthorizationScope contains no allowed roles, departments, ships,
or projects. Intersecting scopes intersects each allowed set and uses the lower
security level, so narrowing can never increase access.
```

- [ ] **Step 3: Run documentation and source formatting checks**

Run:

```bash
git diff --check
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check .
```

Expected: no whitespace errors and Ruff reports `All checks passed!`.

- [ ] **Step 4: Run the focused Task 004 unit tests**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/test_authorization_scope.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Run the relevant integration suite**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_deployment.py tests/integration/test_quality_gate.py -v
```

Expected: all selected integration tests pass.

- [ ] **Step 6: Run the complete quality gate**

Run:

```bash
make check PYTHON=/Users/wuhao/Documents/shipyard-ai/.venv/bin/python
```

Expected: dependency check, all tests, Ruff, and mypy pass.

- [ ] **Step 7: Run explicit final lint and type checks for reporting**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check .
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy .
```

Expected: Ruff reports `All checks passed!`; mypy reports no issues.

- [ ] **Step 8: Commit public documentation**

```bash
git add docs/05-tool-contracts.md docs/06-security.md
git commit -m "docs: define authorization context contract"
```

- [ ] **Step 9: Request an independent principal-engineer review**

Have a separate reviewer read `AGENTS.md`, `tasks/004-auth-context.md`, the
approved design, and the full `origin/main...HEAD` diff. Require findings ranked
P0-P3 with file, line, failure scenario, violated requirement, and smallest safe
fix. Do not modify code during the review.

- [ ] **Step 10: Resolve every P0-P2 finding with TDD**

For each P0-P2 finding, add a focused failing regression test, confirm the
expected RED failure, apply the smallest safe fix, rerun the focused test, rerun
the complete quality gate, and re-review until no P0-P2 findings remain.

- [ ] **Step 11: Evaluate acceptance and stop before Task 005**

Record evidence that identity only comes from the server registry, all scope
dimensions are represented, default scope denies scoped access, intersections
cannot broaden access, tests/Ruff/mypy pass, the deployment artifact contains
the new packages, and no Task 005 files or behavior were started.
