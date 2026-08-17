# Codex Operating Model

## Working model

Treat Codex as a supervised software team, not as one long chat.

Recommended threads:

- Architect
- Backend
- AI/Knowledge
- QA
- Reviewer

## Task execution

For each file under `tasks/`:

1. Create a fresh branch/worktree.
2. Ask Codex to read:
   - `AGENTS.md`
   - the Task
   - referenced docs
3. Codex writes failing tests first.
4. Codex implements only Task scope.
5. Codex runs tests/lint/type checks.
6. A separate Reviewer thread reviews the diff.
7. Fix P0/P1/P2 findings.
8. Human approves merge.

## Generic implementation prompt

Read `AGENTS.md` and `<TASK_FILE>` in full.

Before editing:
- summarize the task in 5 bullets
- identify architecture constraints that apply
- list files you expect to create/modify

Then implement only the task.

Use test-driven development:
1. failing test
2. verify failure
3. minimal implementation
4. focused tests
5. relevant full tests
6. Ruff
7. mypy

At the end report:
- files changed
- tests run and exact results
- architecture decisions
- known limitations
- whether every acceptance criterion passed

Do not start work from the next Task.

## Generic review prompt

Review the current branch as a principal engineer.

Read `AGENTS.md`, the relevant Task, and the diff.

Do NOT modify code.

Prioritize:
- correctness
- authorization bypass
- source-of-truth violations
- unsafe database access
- prompt injection
- evidence/provenance gaps
- hidden coupling
- missing tests
- migration problems
- error/freshness handling

Return findings only, ranked:
P0 Critical
P1 High
P2 Medium
P3 Low

For every finding include:
- file
- line/range
- failure scenario
- why it violates the Task or AGENTS.md
- smallest safe fix
