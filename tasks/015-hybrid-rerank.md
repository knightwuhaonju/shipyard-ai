# Task 015: Hybrid retrieval and reranking

**Dependencies:** 013,014

## Objective

Merge lexical/vector candidates, deduplicate by chunk, add reranker port with fake adapter, and produce ranked Evidence.

## Required reading

- `AGENTS.md`
- `docs/00-product-scope.md`
- relevant architecture document(s)
- this Task file

## Expected files

- `services/retrieval/hybrid.py`
- `services/model_gateway/reranker.py`
- `adapters/reranker/fake.py`
- `tests/unit/retrieval/test_hybrid.py`

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

- [ ] Weights/config are explicit and tested.
- [ ] Duplicate chunks collapse deterministically.
- [ ] Reranker failure degrades to hybrid score with warning.
- [ ] Recall-oriented tests use a curated fixture set.

## Forbidden shortcuts

- Do not start a later Task.
- Do not add unrelated framework abstractions.
- Do not bypass authorization for convenience.
- Do not use real shipyard/customer data.
- Do not add external model dependencies to unit tests.
- Do not weaken `AGENTS.md`.

## Codex prompt

Read `AGENTS.md` and `tasks/015-hybrid-rerank.md` in full. Implement Task 015 only.

Before editing, summarize the architecture constraints that apply and list the files you expect to change.

Use TDD and satisfy every acceptance criterion. At the end, report files changed, exact test/lint/type-check commands and results, architecture decisions, and known limitations. Do not begin Task 016.
