# Reviewer guide

This repository implements an auditable document-to-decision agent for the
Halyk AI Challenge. It is designed around the scoring signals: correct verdict,
correct measured value, and a verdict-determining transaction when one exists.

## Five-minute review path

1. Read the architecture and command overview in `README.md`.
2. Read `CHANGELOG.md` for each measured iteration, regression, and reason for
   changing direction.
3. Inspect `src/halyk_agent/benchmark.py` for evidence assembly and the covenant
   policy, then `src/halyk_agent/consensus.py` for private-answer aggregation.
4. Inspect `tests/test_benchmark.py`, `tests/test_extraction_cascade.py`,
   `tests/test_fx.py`, and `tests/test_consensus.py` for regression coverage.
5. Run `python -m unittest discover -s tests -q`.

## End-to-end decision flow

```text
dataset/template/ledger
        |
        v
PDF native extraction + page-quality and visual-risk routing
        |
        v
OCR fallback merged into the original document provenance
        |
        v
account/entity/version retrieval + deterministic FX/PPE facts
        |
        v
one isolated LLM decision per borrower
        |
        v
independent repetitions -> atomic (status, rounded actual) consensus
        |
        v
template-locked submission.json + auditable evidence trail
```

The public answer key is loaded only by the evaluator after model generation.
Private generation works without `ground_truth.json`. Independent samples never
see one another, which avoids draft anchoring and answer-key leakage.

## Reproducibility and hardcoding boundary

There is no mapping from a private scenario/covenant to a verdict, amount, or
transaction in production code. Fixes discovered during evaluation were encoded
as general evidence rules: final-document precedence, category partitioning,
thresholded EBITDA adjustment bridges, deterministic FX reference pairs,
complete PPE roll-forwards, relationship predicates, and parent-report recovery.

The solver is stochastic, so one model call is not claimed to reproduce an
entire final JSON byte-for-byte. The intended production workflow is repeated
blind solving followed by consensus. Disputed cells can be re-run with
`--scenarios`; that option only filters the template and does not inject an
answer. Source adjudication is performed from independent agent traces, not a
private answer key.

## Evaluation evidence

- 67 deterministic regression tests pass on the final branch.
- The final public ten-repetition baseline had clean mean/min/max `1.0000` with
  zero variance after excluding one confirmed public-key interpretation defect.
- A fresh full public smoke from the final `main` reproduced the same clean
  `1.0000` result.
- The final generic threshold/add-back correction reproduced its
  source-adjudicated private core result in three independent focused runs.
- Private stability and independent source audits covered all template cells;
  no private answer values or source documents are committed here.

The raw public score remains `0.9722` because the published key for `P4/6.3`
predates the organizer's later generic related-party-payment clarification. Both
raw and clean metrics are retained in the iteration history instead of hiding
the discrepancy.

## Runtime audit artifacts

Every run writes ordered artifacts below the selected `--output-dir`:

```text
<provider>/
  events.jsonl          ordered lifecycle, queue, retry, latency, and usage events
  api/                  redacted request/response JSON in sequence order
  prompts/              exact scenario prompts
  corpus/               exact retrieved/normalized evidence sent to the solver
  decisions/            structured decision, explanation, sources, usage, timing
  retrieval.json        document selection and relevance metadata
  submission.json       template-locked generated answer
  evaluation.json       public-only score breakdown
  summary.json          provider-level time and token totals
  repetitions/          independent stability samples, when requested
  stability.json        distributions and flaky-cell report, when requested
```

Authorization headers and credentials are redacted. Document contents and model
conversations are intentionally preserved locally for audit, so `runs/` is
Git-ignored: publishing it would redistribute challenge documents and private
model traces. `CHANGELOG.md` and this guide provide the sanitized review record.

## Key commands

See `README.md` for complete examples. The core review commands are:

```powershell
halyk-agent inspect <dataset>
halyk-agent extract <dataset> --output-dir <documents>
halyk-agent live-eval <dataset> --documents-dir <documents> --output-dir <run>
halyk-agent stability-eval <dataset> --documents-dir <documents> --output-dir <stability>
halyk-agent consensus-submission <stability-provider-dir> <submission.json> --team <team> --contact-email <email>
python -m unittest discover -s tests -q
```
