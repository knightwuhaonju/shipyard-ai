# Task 2 Report — Immutable evidence contracts and lexical retrieval port

## Scope and changed files

Task 2 implemented only the approved transport-independent contract and
retrieval-service boundary:

- Created `packages/contracts/evidence.py`.
- Updated `packages/contracts/__init__.py` without removing the existing
  `AuthorizationScope`, `SecurityLevel`, or `UserContext` exports.
- Created `services/retrieval/__init__.py` and `services/retrieval/lexical.py`.
- Created `tests/unit/retrieval/__init__.py` and
  `tests/unit/retrieval/test_lexical_contracts.py`.
- Created this required report.

No schema, PostgreSQL, infrastructure, ingestion, API, Wiki, Agent, vector,
hybrid, reranking, or business-tool code changed.

## Acceptance and architecture outcome

- `KnowledgeFilters` is frozen, forbids unknown fields, and contains typed
  document-type, ship, and project filters.
- `KnowledgeEvidence` is frozen, forbids unknown fields, preserves required
  document/version/chunk provenance, rejects blank or NUL-bearing text, uses a
  positive exact-integer page, and accepts only finite non-negative scores.
- `LexicalRetriever` accepts a server-derived exact `AuthorizationScope`
  separately from filters, validates exact request types and bounds before port
  invocation, strips a valid query, and delegates unchanged evidence.
- Invalid service inputs return only `invalid lexical retrieval request` and
  never include supplied query or scope data.
- `services.retrieval` imports only `__future__`, `typing`, and
  `packages.contracts`; its unit guard rejects relative and infrastructure
  import bypasses.
- The database ACL predicate, metadata filtering in SQL, ranking, and
  cross-project integration behavior remain deliberately owned by Tasks 3–4.

## TDD evidence

### RED

1. `/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/retrieval/test_lexical_contracts.py -v`
   - Exit 1 as expected: collection failed because `packages.contracts` did not
     export `DocumentType`, `KnowledgeEvidence`, or `KnowledgeFilters`.
2. The same command after adding service delegation tests and before creating
   the retrieval service.
   - Exit 1 as expected: collection failed with `ModuleNotFoundError: No module
     named 'services.retrieval'`.

### GREEN

1. `/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/retrieval/test_lexical_contracts.py -v`
   - 31 passed after the contract implementation.
2. The same command after the retrieval-service implementation.
   - 43 passed.
3. `/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check packages/contracts services/retrieval tests/unit/retrieval`
   - Initial style-only failure (import ordering and two 89+/88-character
     lines); corrected without changing behavior.
4. `/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/retrieval/test_lexical_contracts.py -v`
   - 43 passed after the style correction.
5. `/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check packages/contracts services/retrieval tests/unit/retrieval`
   - Exit 0: all checks passed.
6. `/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy packages/contracts services/retrieval tests/unit/retrieval`
   - Exit 0: success, no issues in 7 source files.

## Final verification

1. `/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit -v`
   - Exit 0: 448 passed.
2. `/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check .`
   - Exit 0: all checks passed.
3. `/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy .`
   - Exit 0: success, no issues in 77 source files.
4. `/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest -v`
   - Exit 0 outside the sandbox: 494 passed and 67 skipped. The skipped tests
     require `TEST_DATABASE_URL`; the initial sandboxed attempt failed only
     because its deployment test was not permitted to bind an ephemeral
     loopback port, and the permitted rerun passed that test.

There is no relevant integration or database suite for this Task 2
contract/service-only change; Task 3 owns the PostgreSQL adapter and its
integration coverage.

## Limitations

The port has no infrastructure implementation yet, so it cannot retrieve data
independently. It intentionally does not implement SQL authorization, result
ranking, evidence assembly from database rows, query wildcard handling, or
cross-project tests; those require the Task 3 PostgreSQL adapter and Task 4
security characterization.

## Commit

Committed as `feat: define lexical retrieval contracts`.
