# Task 004 Authentication Context Design

## Scope

Task 004 introduces transport-independent authentication and authorization
primitives for server-side use. It adds an in-memory local-development
authentication adapter, but no FastAPI integration, external identity provider,
database persistence, tool runtime, or Task 005 domain behavior.

## Architecture Constraints

- Authentication and authorization remain separate concerns.
- Authenticated identity is supplied by the host service, never by model or
  tool arguments.
- Authorization is derived server-side and is deny-by-default.
- Contracts remain independent of FastAPI, databases, LLM SDKs, and transports.
- Downstream services receive a typed `UserContext` or `AuthorizationScope`
  through a trusted parameter that is separate from model-generated business
  arguments.
- The local adapter uses synthetic development identities only and does not log
  credentials or identity payloads.
- Task 004 does not implement a tool registry, API authentication middleware,
  external IdP integration, or any Task 005 behavior.

## Components

### Authentication contracts

`packages/contracts/auth.py` defines immutable Pydantic value objects with
unknown fields forbidden:

- `SecurityLevel` is an ordered enumeration with the levels `PUBLIC`,
  `INTERNAL`, `CONFIDENTIAL`, and `RESTRICTED`, in ascending order.
- `UserContext` contains `user_id`, roles, departments, allowed ship IDs,
  allowed project IDs, and security clearance. It represents claims that have
  already been authenticated by a trusted host adapter.
- `AuthorizationScope` contains the corresponding role, department, ship,
  project, and security constraints. Its no-argument value contains no allowed
  set members and is therefore deny-by-default for scoped resources.

Set-valued fields use immutable sets so callers cannot mutate an authenticated
identity or derived scope after validation. Identifiers are non-empty strings.

### Authorization service

`services/auth/service.py` provides one pure function,
`authorization_scope_for(user_context, requested_scope=None)`, that:

1. derives an `AuthorizationScope` from an authenticated `UserContext`; and
2. optionally narrows that scope by intersecting it with an explicitly supplied
   requested scope.

Intersection is monotonic: roles, departments, ship IDs, and project IDs use set
intersection, while security clearance uses the lower of the two ordered
levels. A requested scope can remove permissions but cannot add any permission
that the authenticated user does not already hold. No-overlap results remain
empty rather than falling back to a broader scope.

### Local authentication adapter

`adapters/auth/local.py` implements a development-only adapter backed by an
in-memory server-side registry. The adapter receives only an opaque development
credential and resolves it to a preconfigured `UserContext`. The public
authentication operation does not accept `user_id`, roles, departments, ship
IDs, project IDs, or security clearance as caller-supplied claims.

The concrete API is `LocalAuthenticationAdapter.authenticate(credential)`. Its
constructor copies a server-provided mapping from credentials to contexts so a
caller cannot mutate the adapter's registry after construction.

Missing and unknown credentials raise the same `AuthenticationError`. The error
message is generic and never includes the credential or registry contents. The
adapter performs no network, filesystem, database, or external IdP access.

## Data Flow

1. A trusted API host obtains the development credential from its transport.
2. The host passes only that credential to the local authentication adapter.
3. The adapter resolves a registered immutable `UserContext`.
4. The authorization service derives the user's full `AuthorizationScope`.
5. If an operation supplies a narrower scope constraint, the service intersects
   it with the user scope.
6. The host passes the resulting trusted context or scope to downstream
   services separately from model-generated business arguments.

This boundary prevents a model-generated mapping containing fields such as
`user_id`, `roles`, or `allowed_project_ids` from becoming authenticated claims.
Later tool-runtime work will be responsible for injecting the trusted context,
but that runtime is not part of Task 004.

## Failure and Security Behavior

- An empty `AuthorizationScope` grants no members in any scoped dimension.
- Empty intersections stay empty and never broaden access.
- A requested higher security level is capped by the authenticated user's
  clearance.
- Pydantic rejects extra fields instead of silently ignoring identity overrides.
- Missing and unknown local credentials are indistinguishable to callers.
- Credential values are not included in exceptions, representations, or logs.
- The contracts and service do not trust untyped mappings as authenticated
  identities.

## Testing Strategy

Development follows RED-GREEN-REFACTOR for each behavior:

1. A focused failing test establishes default-deny scope construction and full
   scope-intersection behavior.
2. Minimal contracts and ordered security levels make those tests pass.
3. Focused failing tests establish exact scope derivation and monotonic
   narrowing by the authorization service.
4. Focused failing tests establish registry-derived local identity, rejection
   of caller-supplied identity claims, and safe failure for missing or unknown
   credentials.
5. Edge tests cover disjoint sets, higher requested clearance, immutable values,
   forbidden extra fields, and credential-free error messages.

All tests use synthetic values and make no network, database, filesystem, or
external model calls. Verification runs the focused Task 004 tests, the complete
unit and relevant integration suites, `ruff check .`, and `mypy .`.

## Expected Changes

- `packages/contracts/__init__.py`
- `packages/contracts/auth.py`
- `services/__init__.py`
- `services/auth/__init__.py`
- `services/auth/service.py`
- `adapters/__init__.py`
- `adapters/auth/__init__.py`
- `adapters/auth/local.py`
- `tests/unit/test_authorization_scope.py`
- `tests/integration/test_deployment.py`
- `docs/05-tool-contracts.md`
- `docs/06-security.md`
- `docs/superpowers/plans/2026-08-17-auth-context.md`
- `pyproject.toml`
- `Dockerfile`

The package marker files are included only where required for packaging and
static analysis. `pyproject.toml` adds `services*` and `adapters*` to package
discovery because Task 004 introduces those top-level packages. `Dockerfile`
copies both package trees into its build context, and the deployment packaging
test verifies that the installed artifact can import the new public contracts,
service, and adapter from an isolated directory. No schema migration or new
runtime dependency is required.

## Acceptance Mapping

- Identity cannot be supplied through model/tool arguments: the adapter accepts
  only a credential and returns server-registered claims; trusted context is a
  separate downstream parameter.
- Role, department, ship/project scope, and security level: all are explicit in
  the contracts and authorization service.
- Deny-by-default: the default scope has empty allowed sets.
- Scope intersection: set dimensions intersect and clearance takes the lower
  ordered level, with focused unit coverage.

## Known Limitations

- The local registry is development-only and has no persistence, password
  verification, token validation, expiry, revocation, or rotation.
- Task 004 defines the trusted boundary but does not wire it into FastAPI or a
  tool runtime.
- Resource-specific authorization decisions remain the responsibility of the
  later retrieval and tool services, which must evaluate the relevant scope
  dimensions before access.
