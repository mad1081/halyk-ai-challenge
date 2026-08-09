# Architecture

## Design goals

1. **Reproducible:** every run has immutable inputs, configuration and output
   manifests.
2. **Auditable:** every fact and decision will retain its source document,
   page, extraction backend and supporting transaction IDs.
3. **Deterministic where possible:** parsing orchestration, joins, currency
   conversion, arithmetic, scoring and JSON validation are code, not prose
   prompts.
4. **Replaceable:** OCR, LLM, retrieval and prompt variants are adapters behind
   stable schemas.

## Implemented pipeline

```text
dataset ZIP/directory
  -> dataset validation + fingerprint
  -> scenario/account mapping
  -> per-page PDF classification and extraction cascade
  -> document catalog (borrower, type, date, version, status)
  -> current-document resolver
  -> structured covenant and supporting-fact extraction
  -> transaction classification
  -> deterministic calculation
  -> independent repetitions + atomic consensus
  -> schema validation
  -> submission.json
```

## Extraction policy

Any successful parser process can still return useless text. Selection is
therefore based on content quality, not exit code alone. The current gate uses
character count, alphabetic-character count, replacement-character ratio and
line count. It also checks native text per page and routes substantial raster
regions by displayed page coverage, so a scanned table cannot hide inside an
otherwise searchable PDF. Financial identifiers and amounts are retained in
the evidence corpus for source-grounded comparison by the solver.

The implemented backends are:

- **AnyDoc:** fast Markdown for text-native PDFs, isolated in a subprocess.
- **pdftotext:** independent native fallback for text-native PDFs.
- **Docling + RapidOCR:** layout/table-aware local fallback for scanned and
  mixed PDFs in Russian, Kazakh and English.
- **OCRmyPDF:** optional local OCR pass for scanned/mixed PDFs, followed by
  `pdftotext`.
- **Provider vision OCR:** selected suspicious pages only, parallelized by
  source document and merged back with account provenance.

AnyDoc 0.1.6 delegates PDF parsing to `pdf-inspector` and does not perform OCR.
Its locked `lopdf` 0.41.0 dependency has a published denial-of-service issue,
so it must not run in-process on arbitrary uploads. For this synthetic corpus
it remains behind per-file process isolation and timeouts; independent native,
local OCR, and provider-vision backends cover its failure modes.

## Run artifacts

Generated files live under `runs/<run-id>/` and never enter Git. Source code,
schemas and experiment summaries are versioned. Current run artifacts record:

- dataset SHA-256 fingerprint;
- model and reasoning settings;
- exact prompts, schemas, retrieved corpus and structured decisions;
- per-document extraction attempts and provenance;
- latency/token usage;
- public evaluation score.

## Security boundaries

- Treat PDFs and archives as untrusted input.
- Reject ZIP path traversal before extraction.
- Parse each PDF in a separate process with a deadline.
- Never interpolate document paths into a shell string.
- Keep API keys in environment variables and out of prompts, logs and Git.
- Do not send the public `ground_truth.json` to the solving model.
