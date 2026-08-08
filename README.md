# Halyk AI Challenge Agent

An auditable pipeline for turning a Halyk challenge dataset into covenant
decisions. The repository keeps deterministic ingestion, extraction, financial
calculation and evaluation separate from LLM judgment so each layer can be
tested and replaced independently.

## Current MVP

The first milestone implements the deterministic foundation:

- accepts an extracted dataset directory or ZIP archive;
- validates the ledger, document directory and submission template;
- derives the exact `scenario_id -> account_id` mapping from transaction IDs;
- creates a reproducible run directory with manifests and a draft submission;
- extracts PDF text through an isolated AnyDoc process, `pdftotext`, and an
  optional OCRmyPDF fallback;
- scores extraction quality and records every attempted backend;
- evaluates a generated submission against the public `ground_truth.json`.

The LLM covenant solver is the next milestone. The current `mvp` command does
not pretend that unresolved `null` cells are final answers.

## Quick start

Requires Python 3.11 or newer. The core has no third-party Python dependency.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .

halyk-agent inspect .\agentic-bank-public
halyk-agent mvp .\agentic-bank-public --work-dir .\runs\public
```

The `mvp` command writes:

```text
runs/public/
  dataset-summary.json
  scenario-accounts.json
  submission.draft.json
```

## PDF extraction

The repository supports a cascade instead of trusting one parser:

1. AnyDoc in a separate Python process with a timeout.
2. `pdftotext` for a second native text extraction attempt.
3. Docling plus RapidOCR for scanned/mixed documents and complex tables.
4. OCRmyPDF plus `pdftotext` as a last local fallback, when installed.

Use the already isolated AnyDoc environment:

```powershell
halyk-agent extract .\agentic-bank-public `
  --output-dir .\runs\public\documents `
  --anydoc-python .\.venv-anydoc\Scripts\python.exe `
  --limit 10
```

Process every PDF by omitting `--limit`. All generated Markdown and manifests
belong under `runs/`, which is intentionally ignored by Git.

For the recommended scanned-PDF fallback, use a separate Python 3.12
environment and pre-download models before the private round:

```powershell
uv venv .venv-docling --python 3.12
uv pip install --python .\.venv-docling\Scripts\python.exe docling rapidocr onnxruntime
.\.venv-docling\Scripts\docling-tools.exe models download layout tableformer rapidocr `
  --rapidocr-backend-lang onnxruntime:cyrillic
```

Then put `.venv-docling\Scripts` on `PATH` for the run, or pass the full
Docling executable through `--docling-command`.

AnyDoc 0.1.6 is treated as an untrusted parser dependency and is always run in
a child process. See [architecture notes](docs/ARCHITECTURE.md) for the reason
and [OCR research](docs/OCR_RESEARCH.md) for the tiered fallback strategy.

## Evaluation

```powershell
halyk-agent evaluate .\candidate-submission.json `
  .\agentic-bank-public\ground_truth.json
```

The reported score reproduces the documented unweighted per-cell score. The
organizer's hidden difficulty weights are not present in the public files, so
the CLI labels this result as a proxy score.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Git workflow

- `main`: runnable, tested baseline.
- `experiment/ocr-*`: alternative extraction/OCR stacks.
- `experiment/prompt-*`: prompt and model experiments.
- `experiment/retrieval-*`: retrieval and document-versioning experiments.

Create an experiment branch only when an actual experiment starts. Record its
dataset fingerprint, configuration and score in `docs/EXPERIMENTS.md` before
merging a winner into `main`.
