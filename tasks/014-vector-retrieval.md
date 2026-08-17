# Task 014: Vector retrieval with pgvector

**Dependencies:** 013

## Objective

Implement embedding port, fake deterministic embedding adapter, pgvector storage/index, and ACL-filtered vector retrieval.

## Required reading

- `AGENTS.md`
- `docs/00-product-scope.md`
- relevant architecture document(s)
- this Task file

## Expected files

- `services/model_gateway/embedding.py`
- `adapters/embedding/fake.py`
- `services/retrieval/vector.py`
- `alembic/versions/*`
- `tests/integration/retrieval/test_vector_acl.py`

Codex may adjust exact paths to match the repository state, but must preserve subsystem boundaries and explain any path change.

## Implementation protocol

- [ ] Read existing code before editing.
- [ ] State the files expected to change.
- [ ] Write the first failing test for the primary behavior.
- [ ] Run the focused test and confirm failure.
- [ ] Implement the minimum code needed.
- [ ] Run the focused test and confirm pass.
- [ ] Add failure/edge/security tests required by this Task.
- [ ] Run the relevant integration suite.
- [ ] Run `ruff check .`.
- [ ] Run `mypy .`.
- [ ] Update public contract/docs only if the Task changes them.
- [ ] Report exact commands and results.

## Acceptance criteria

- [ ] Unit/integration tests never require external model.
- [ ] Embedding dimension is configuration-controlled.
- [ ] ACL is enforced before/with vector query.
- [ ] Evidence contains vector score.

## Forbidden shortcuts

- Do not start a later Task.
- Do not add unrelated framework abstractions.
- Do not bypass authorization for convenience.
- Do not use real shipyard/customer data.
- Do not add external model dependencies to unit tests.
- Do not weaken `AGENTS.md`.

## Codex prompt

Read `AGENTS.md` and `tasks/014-vector-retrieval.md` in full. Implement Task 014 only.

Before editing, summarize the architecture constraints that apply and list the files you expect to change.

Use TDD and satisfy every acceptance criterion. At the end, report files changed, exact test/lint/type-check commands and results, architecture decisions, and known limitations. Do not begin Task 015.
