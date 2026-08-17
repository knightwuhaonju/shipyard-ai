# Evaluation Design V1

## Eval categories

### Retrieval

- Recall@10
- MRR / rank quality
- citation correctness
- authorization-safe retrieval

### Tools

- tool selection
- argument extraction
- typed output correctness
- error/freshness handling

### Agent

- answer groundedness
- evidence coverage
- unsupported inference rate
- conflicting-source behavior

### Security

- unauthorized ship/project query
- role boundary
- prompt injection
- SQL-like malicious input
- model attempt to call hidden tool

## Dataset

Start with synthetic fixtures, then add validated pilot questions.

Target before pilot:

- 100+ knowledge questions
- 50+ project questions
- 50+ procurement questions
- 30+ drawing/BOM questions
- 50+ security/adversarial questions

Each item has:

- id
- question
- user context
- expected intent
- expected tools optional
- ground truth
- accepted evidence
- prohibited evidence
- grading method

## Release gate

Pilot release must pass:

- no P0/P1 security finding
- all deterministic contract tests
- no known cross-scope retrieval leak
- evidence attached to factual answers
- explicit stale-data warnings when applicable
