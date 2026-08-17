# Shipyard Agent V1 Design

## Principle

One Agent, many typed tools.

No multi-agent system in V1.

## Supported intents

- KNOWLEDGE_QUERY
- PROJECT_STATUS
- PROCUREMENT_STATUS
- DRAWING_BOM
- PROJECT_RISK
- GENERAL_ANALYSIS

## Execution model

```text
question
 -> normalize user context
 -> classify intent
 -> choose bounded tool plan
 -> execute tools
 -> aggregate evidence
 -> synthesize answer
 -> emit trace metadata
```

## Tool constraints

Agent only sees registered tool schemas.

The Agent cannot:

- access database credentials
- issue arbitrary HTTP requests
- browse filesystem
- execute shell commands
- execute generated SQL directly
- write to business systems
- promote Wiki state

## Response envelope

- answer
- confidence
- evidence[]
- tool_calls[]
- data_freshness[]
- warnings[]

## Risk analysis

V1 risk summaries are deterministic where possible.

Example procurement risk features:

- required date passed and not delivered
- promised date after required date
- remaining buffer
- criticality
- historical supplier delay feature, if available

LLM may summarize those features but must not manufacture a probability unless a validated risk model produces one.
