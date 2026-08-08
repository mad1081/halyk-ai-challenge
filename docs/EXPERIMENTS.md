# Experiment log

Record comparable experiments here. Generated raw artifacts stay in `runs/`.

| ID | Branch/commit | Dataset | Change | Score | Latency | Decision |
|---|---|---|---|---:|---:|---|
| baseline-000 | `main` | public-v1 | Deterministic ingestion/eval scaffold | N/A | N/A | Foundation |
| public-openai-001 | working tree | `f4fe39f...` | `gpt-5.6-sol`, original sequential live baseline | 0.7861 | 13.92 min | Current accuracy leader; rerun with concurrency later |
| public-anthropic-001 | working tree | `f4fe39f...` | `claude-sonnet-5`, 7 concurrent scenario calls | 0.7000 | 10.07 min | Complete baseline; improve retrieval/calculation before model tuning |
| public-openai-stability-10x-001 | working tree | public-v1 | `gpt-5.6-sol`, 10 repetitions, 35-worker bounded pool, one shared OCR pass | 0.7848 mean (0.7167-0.8417) | 7.43 min | Frozen v1 baseline; 120/120 solver tasks completed |
| public-anthropic-stability-10x-001 | working tree | public-v1 | `claude-sonnet-5`, 10 repetitions, 35-worker bounded pool, one shared OCR pass | 0.7219 mean (0.6278-0.7806) | 21.18 min | Frozen v1 baseline; 119/120 tasks completed, one P3 exhausted retries |

The OpenAI and Anthropic wall times are not a clean speed comparison: OpenAI
was collected before concurrent scenario execution was added, while Anthropic
used concurrency 7. The Anthropic run completed all 12 scenarios with no final
failures; P3 required a second attempt after hitting its 32,768-token ceiling.

## Frozen v1 stability baseline (10 repetitions)

Raw artifacts are under `runs/evals/public-v1-stability-10x-20260809/` and are
not committed because they contain full API requests/responses. `P4/6.3` is
retained in the official proxy score, but excluded from the diagnostic clean
score because the public contract threshold and ground truth are known to
conflict. Mean clean scores are 0.8072 for OpenAI and 0.7426 for Anthropic.

The repeated run shows that v1 failures are not explained by random sampling:

- both providers failed `P2/6.3` and `P5/6.1` in all 10 repetitions;
- both providers systematically omitted required evidence transaction IDs for
  several breach cells (`B1/6.1`, `P8/6.3`, and others);
- OpenAI averaged 85.0% status accuracy, with 20-24 perfect cells per run;
- Anthropic averaged 76.1% status accuracy, with 20-26 perfect cells per run;
- P3 is the latency and output-limit outlier. One Anthropic P3 task failed after
  three `max_tokens` responses and took 930 seconds; other P3 tasks frequently
  required retries.

Decision: keep the OCR result shared and cached, retain OpenAI as the current
default solver, and improve document/entity retrieval, evidence selection, and
deterministic calculation before tuning model effort. Add a hard wall-clock
deadline so a single pathological request cannot hold the entire private run.

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
