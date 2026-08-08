# Changelog

All notable implementation changes and experiment decisions are recorded here.

## [Unreleased]

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
