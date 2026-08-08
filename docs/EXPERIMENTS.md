# Experiment log

Record comparable experiments here. Generated raw artifacts stay in `runs/`.

| ID | Branch/commit | Dataset | Change | Score | Latency | Decision |
|---|---|---|---|---:|---:|---|
| baseline-000 | `main` | public-v1 | Deterministic ingestion/eval scaffold | N/A | N/A | Foundation |
| public-openai-001 | working tree | `f4fe39f...` | `gpt-5.6-sol`, original sequential live baseline | 0.7861 | 13.92 min | Current accuracy leader; rerun with concurrency later |
| public-anthropic-001 | working tree | `f4fe39f...` | `claude-sonnet-5`, 7 concurrent scenario calls | 0.7000 | 10.07 min | Complete baseline; improve retrieval/calculation before model tuning |

The OpenAI and Anthropic wall times are not a clean speed comparison: OpenAI
was collected before concurrent scenario execution was added, while Anthropic
used concurrency 7. The Anthropic run completed all 12 scenarios with no final
failures; P3 required a second attempt after hitting its 32,768-token ceiling.

## Experiment template

```markdown
### experiment-id

- Commit:
- Dataset fingerprint:
- Model / effort:
- Extractor configuration:
- Prompt/schema version:
- Score (overall/status/actual/evidence):
- Runtime and token usage:
- Observed failure modes:
- Decision:
```
