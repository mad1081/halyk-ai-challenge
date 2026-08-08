# Changelog

All notable implementation changes and experiment decisions are recorded here.

## [Unreleased]

### v2.3 — currency/category stability baseline

**What changed:** Added an explicit all-currency check and prohibited silently
folding social or other taxes into personnel expense. Measured the solver over
10 independent full public runs (120 borrower calls) with 35-way concurrency.

**Why:** A single v2.2 run missed one relevant EUR operating-services row and
occasionally broadened narrow covenant categories. One-off eval scores could
not distinguish a prompt defect from sampling variance.

**Result:** All 120 calls completed in 5.90 minutes. Excluding the confirmed
P4/6.3 public-key conflict, the mean score was 0.9649 (min 0.9429, max 0.9921).
32/35 scored cells were perfect in all 10 runs. The remaining flaky cells are
P3/6.1 (3/10 perfect), P6/6.2 (5/10), and P7/6.1 (9/10).

**Rejected experiment:** A second LLM pass that saw and rewrote the first
draft reduced one measured run from 34 to 32 perfect cells, increased tokens
from roughly 203K to 428K, and failed to catch the P7 double-count. It is not
part of the pipeline. Any future ensemble must use independent samples plus a
deterministic calculation validator or majority consensus.

**Next:** Add a structured, covenant-specific calculation ledger with explicit
category membership, currency conversion, and duplicate-category checks; then
rerun the same stability harness.

### v2.2 — page-aware retrieval and OCR

**What changed:** Added borrower-entity second-hop retrieval, compact
covenant-focused evidence, explicit version/classification/calculation rules,
page-level native-text checks, substantial embedded-image detection, and
parallel vision OCR for every routed source PDF. Added a 600-second hard
scenario deadline and raised OpenAI's structured-output ceiling to 16,384.

**Why:** The v1 agent sent roughly 200K prompt characters per borrower yet
systematically missed an account-less group report and three tables hidden as
single scanned pages inside otherwise searchable PDFs. Whole-document quality
scores marked those mixed PDFs as successful.

**Result:** OpenAI public proxy improved from a 10-run v1 mean of 0.7848
(best 0.8417) to 0.9167, with 33/36 perfect cells in 2.32 minutes. Excluding
the confirmed P4/6.3 public-key conflict, the diagnostic score is 0.9429.
Page-aware OCR fixed P2/6.3, P4/6.1, and P9/6.1; all four scanned/mixed public
documents (seven pages) are now detected automatically.

**Next:** Add an independent calculation verifier and measure v2.2 stability;
the two remaining non-key errors were cells that v2.1 had already answered
correctly, suggesting solve variance rather than missing OCR evidence.

### Added

- `.env` configuration for either `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`.
- Automatic credential-based provider selection with configurable priority.
- Provider-neutral strict JSON Schema client for OpenAI Responses and
  Anthropic Messages APIs.
- Secret-safe `llm-status` CLI command and mocked provider request tests.
- End-to-end `live-eval` covenant agent with account-based document retrieval,
  vision OCR for scan pages, strict structured decisions, submission generation,
  and public-ground-truth scoring.
- Full prompt, redacted request, response, decision, and append-only JSONL logs.
- Per-attempt, per-scenario, OCR, queue, provider, and benchmark timings in both
  seconds and minutes.
- Configurable concurrent scenario execution (`--concurrency`, default 7) for
  both OpenAI and Anthropic.
- Thread-safety tests for concurrent artifact/event logging.
- Repeated stability evaluation with shared OCR, parallel providers, bounded
  per-provider concurrency, independent submissions, and per-cell answer/score
  distributions.
- Diagnostic clean-score exclusions that leave the official proxy untouched.
- Bounded retry backoff with jitter for rate limits and transient API failures.

### Changed

- Default Anthropic model changed to `claude-sonnet-5` for routine agent runs.
- Default API timeout increased from 180 to 600 seconds after concurrent Sonnet
  calls legitimately exceeded three minutes.
- Provider-specific output ceilings can be set with
  `OPENAI_MAX_OUTPUT_TOKENS` and `ANTHROPIC_MAX_OUTPUT_TOKENS`.

## [0.1.0] - 2026-08-08

### Added

- Python package and `halyk-agent` CLI.
- Directory/ZIP dataset discovery with safe archive extraction.
- Ledger parsing and target scenario-to-account mapping.
- Reproducible MVP run manifests and draft submission generation.
- Isolated AnyDoc, `pdftotext`, and optional OCRmyPDF extraction cascade.
- Optional Docling + RapidOCR scanned/mixed-PDF fallback.
- Extraction quality gate and attempt manifest.
- Public ground-truth evaluation harness.
- Unit tests and project documentation.
