# Task 012: Optional scanned-PDF OCR adapter

**Dependencies:** 010

## Objective

Add an OCR port and an optional local adapter boundary for scanned PDFs. Keep OCR dependency optional and disabled by default.

## Required reading

- `AGENTS.md`
- `docs/00-product-scope.md`
- relevant architecture document(s)
- this Task file

## Expected files

- `services/ingestion/ocr.py`
- `adapters/ocr/fake.py`
- `tests/unit/ingestion/test_ocr_flow.py`

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

- [ ] Scanned PDF is detected and returns OCR_REQUIRED when adapter disabled.
- [ ] OCR result preserves page numbers.
- [ ] No OCR engine leaks into domain/service interfaces.
- [ ] Tests use fake OCR adapter.

## Forbidden shortcuts

- Do not start a later Task.
- Do not add unrelated framework abstractions.
- Do not bypass authorization for convenience.
- Do not use real shipyard/customer data.
- Do not add external model dependencies to unit tests.
- Do not weaken `AGENTS.md`.

## Codex prompt

Read `AGENTS.md` and `tasks/012-ocr-adapter.md` in full. Implement Task 012 only.

Before editing, summarize the architecture constraints that apply and list the files you expect to change.

Use TDD and satisfy every acceptance criterion. At the end, report files changed, exact test/lint/type-check commands and results, architecture decisions, and known limitations. Do not begin Task 013.
