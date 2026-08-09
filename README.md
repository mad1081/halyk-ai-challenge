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
- extracts PDF text through an isolated AnyDoc process and independent
  fallbacks;
- scores whole-document and per-page quality, routing blank or substantial
  embedded-image pages to vision OCR;
- evaluates a generated submission against the public `ground_truth.json`.

The live covenant solver is implemented as an auditable baseline. It retrieves
documents by borrower account, sends one structured task per scenario, writes a
submission, and scores it against public ground truth. The `mvp` command remains
the deterministic no-API inspection path.

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

## LLM credentials

Copy `.env.example` to `.env` and fill either key; one key is enough:

```dotenv
OPENAI_API_KEY=your-openai-key
# ANTHROPIC_API_KEY=your-anthropic-key
```

Or use Anthropic only:

```dotenv
# OPENAI_API_KEY=your-openai-key
ANTHROPIC_API_KEY=your-anthropic-key
```

With `HALYK_LLM_PROVIDER=auto`, the agent selects the credential that exists.
If both exist, `HALYK_LLM_PRIORITY=openai,anthropic` controls the choice. Set
`HALYK_LLM_PROVIDER=openai` or `anthropic` to force one explicitly. Process
environment variables override values in `.env`.

Verify selection without making or billing an API request:

```powershell
Copy-Item .env.example .env
# Edit .env, then:
halyk-agent llm-status
```

The command never prints the key. The shared client uses OpenAI Responses API
or Anthropic Messages API and requests strict JSON Schema output from either
provider. `.env` is ignored by Git.

## Live model evaluation

After extraction, run either or both providers. Scenario calls use seven worker
threads by default. Independent scanned documents are OCRed concurrently before
the scenario pool because their transcripts may be required evidence.

```powershell
halyk-agent live-eval .\agentic-bank-public `
  --documents-dir .\runs\public\documents `
  --scan-images-dir .\runs\public `
  --output-dir .\runs\evals\trial-001 `
  --providers anthropic `
  --concurrency 7
```

`--scan-images-dir` may point either to one directory of PNG pages or to an
extraction root containing multiple `scan-<pdf-stem>` directories. If omitted,
the command discovers those sibling directories next to `--documents-dir`.

The same command is the private-dataset generator. When `ground_truth.json` is
absent it writes the completed submission without attempting to score it;
submission identity is required explicitly so an upload cannot retain local
benchmark placeholders:

```powershell
halyk-agent live-eval .\agentic-bank-private `
  --documents-dir .\runs\private\documents `
  --scan-images-dir .\runs\private `
  --output-dir .\runs\private-final `
  --providers openai `
  --concurrency 12 `
  --team "YOUR TEAM" `
  --contact-email "YOUR EMAIL"
```

The upload candidate is `runs/private-final/openai/submission.json`. Its
summary contains `"evaluation": null` because private truth is unavailable.

Each provider directory contains `events.jsonl`, complete redacted API
request/response JSON, prompts, decisions, OCR transcript, `submission.json`,
`evaluation.json`, and `summary.json`. Timings include seconds and minutes for
every API attempt, OCR, queue wait, scenario, provider run, and whole benchmark.
Authorization headers are redacted; document contents and model conversations
are intentionally retained for audit, so do not publish `runs/`.

For a statistically meaningful frozen baseline, repeat the same retrieval and
prompt while sharing one OCR transcript per provider:

```powershell
halyk-agent stability-eval .\agentic-bank-public `
  --documents-dir .\runs\public\documents `
  --scan-images-dir .\runs\public\scan-pages `
  --output-dir .\runs\evals\stability-v1 `
  --providers openai anthropic `
  --repetitions 10 `
  --concurrency 35 `
  --exclude-cell P4/6.3
```

OpenAI and Anthropic run in parallel, with `--concurrency` applied separately to
each provider. `stability.json` reports score distribution, answer distribution,
and `0/N` stable failures versus flaky cells. Exclusions never change the normal
proxy score; they produce a second diagnostic score for confirmed public-key
defects.

For a private dataset, aggregate the independent OpenAI repetitions without
showing any sample another sample's answer:

```powershell
halyk-agent consensus-submission `
  .\runs\private-stability\openai `
  .\runs\private-final\submission.json `
  --team "YOUR TEAM" `
  --contact-email "YOUR EMAIL"
```

Consensus votes on the inseparable `(status, actual rounded to two decimals)`
pair, rather than mixing fields from incompatible calculations. A core tie
fails closed for explicit adjudication. For a consensus breach, the most
supported non-null evidence candidate is retained; compliant cells use null.

To re-run only a disputed scenario against the same corpus and prompt:

```powershell
halyk-agent live-eval .\agentic-bank-private `
  --documents-dir .\runs\private\documents `
  --output-dir .\runs\focused-check `
  --providers openai `
  --scenarios B1 `
  --team "YOUR TEAM" `
  --contact-email "YOUR EMAIL"
```

The scenario ID above is illustrative; no borrower or answer overrides are
embedded in the solver.

## PDF extraction

The repository supports a routed cascade instead of trusting one parser:

1. AnyDoc in a separate Python process with a timeout.
2. `pdftotext` for a second native text extraction attempt and page coverage.
3. `pdfimages` detection for substantial raster regions on otherwise text-rich
   hybrid pages.
4. Selected pages rasterized at 200 DPI and sent to provider vision OCR; GPT-5.6
   uses `detail: original`.
5. Docling plus RapidOCR for local scanned/mixed-document and table fallback.
6. OCRmyPDF plus `pdftotext` as an emergency local fallback, when installed.

Use the already isolated AnyDoc environment:

```powershell
halyk-agent extract .\agentic-bank-public `
  --output-dir .\runs\public\documents `
  --anydoc-python .\.venv-anydoc\Scripts\python.exe `
  --limit 10
```

Process every PDF by omitting `--limit`. Extraction creates Markdown plus
`scan-<pdf-stem>/page-NNNN.png` only for routed pages. All generated artifacts
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
