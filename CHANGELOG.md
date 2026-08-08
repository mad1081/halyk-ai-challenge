# Changelog

All notable implementation changes and experiment decisions are recorded here.

## [Unreleased]

### Planned

- Structured document catalog and version resolver.
- Covenant extraction prompts and solver orchestration.
- Deterministic financial calculation engine.
- End-to-end public-dataset evaluation.

### Added

- `.env` configuration for either `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`.
- Automatic credential-based provider selection with configurable priority.
- Provider-neutral strict JSON Schema client for OpenAI Responses and
  Anthropic Messages APIs.
- Secret-safe `llm-status` CLI command and mocked provider request tests.

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
