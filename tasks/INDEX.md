# Codex Task Index

按编号执行；只有标注为无依赖或依赖已完成的任务才可启动。

| Task | Title | Dependencies |
|---:|---|---|
| 001 | [Repository bootstrap](001-repository-bootstrap.md) | None |
| 002 | [CI and quality gates](002-ci-quality-gates.md) | 001 |
| 003 | [Configuration and structured logging](003-configuration-logging.md) | 001 |
| 004 | [Authentication stub and authorization context](004-auth-context.md) | 003 |
| 005 | [Core Shipyard domain entities](005-domain-core.md) | 001,003 |
| 006 | [Domain persistence and migrations](006-domain-persistence.md) | 005 |
| 007 | [Entity aliases and canonicalization](007-entity-aliases.md) | 006 |
| 008 | [Synthetic shipyard fixture dataset](008-synthetic-fixtures.md) | 006,007 |
| 009 | [Document/version/chunk schema](009-document-schema.md) | 006 |
| 010 | [File parser adapters](010-parser-adapters.md) | 009 |
| 011 | [Structure-aware chunking](011-structural-chunking.md) | 010 |
| 012 | [Optional scanned-PDF OCR adapter](012-ocr-adapter.md) | 010 |
| 013 | [Lexical retrieval](013-lexical-retrieval.md) | 009,011 |
| 014 | [Vector retrieval with pgvector](014-vector-retrieval.md) | 013 |
| 015 | [Hybrid retrieval and reranking](015-hybrid-rerank.md) | 013,014 |
| 016 | [Knowledge search API and citations](016-knowledge-api.md) | 015,004 |
| 017 | [LLM Wiki persistence model](017-wiki-schema.md) | 006,009 |
| 018 | [Wiki review and promotion workflow](018-wiki-review-workflow.md) | 017,004 |
| 019 | [Wiki draft compiler](019-wiki-compiler.md) | 015,017 |
| 020 | [Wiki search tool service](020-wiki-search.md) | 017,018 |
| 021 | [Typed tool runtime and audit](021-tool-runtime.md) | 004,008 |
| 022 | [Knowledge and Wiki tools](022-knowledge-tools.md) | 016,020,021 |
| 023 | [Mock ship/project/procurement/drawing tools](023-business-mock-tools.md) | 008,021 |
| 024 | [ERP/MES/PLM adapter ports and MCP adapter](024-source-adapter-ports-mcp.md) | 021,023 |
| 025 | [Agent intent router](025-agent-router.md) | 022,023 |
| 026 | [Bounded Agent tool execution loop](026-agent-tool-loop.md) | 021,025 |
| 027 | [Grounded answer synthesis and response envelope](027-answer-synthesis.md) | 026,022,023 |
| 028 | [Evaluation dataset and runner](028-eval-platform.md) | 015,23,27 |
| 029 | [Security adversarial suite](029-security-hardening.md) | 016,20,23,27,28 |
| 030 | [Pilot UI and end-to-end demo](030-pilot-ui-e2e.md) | 016,27,29 |
