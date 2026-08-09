# Changelog

All notable implementation changes and experiment decisions are recorded here.

## [Unreleased]

### Experiment — deterministic FX normalization

**What changed:** Added a source-grounded FX-pair extractor and a deterministic
prompt section that derives unit rates with `Decimal`, links them to non-USD
ledger rows by currency and counterparty, preserves transaction signs, and
shows the exact conversion formula and provenance.

**Why:** In the v2.3 stability baseline, P3/6.1 was correct in only 3/10 runs.
Seven runs mistook the USD side of a small auditor reference pair for the USD
value of a different, much larger EUR transaction. The relevant document and
ledger row had been retrieved in every run, so this is a calculation-structure
experiment rather than another retrieval or LLM-review pass.

**Safety:** Conflicting rates are reported and never selected automatically;
rows without an explicit counterparty-linked reference pair are unchanged.
Five focused tests cover derived rates, exact reference matches, signs,
conflicts, missing links, and European number separators. Full paid stability
evaluation remains pending.

### Experiment refinement — FX normalization preserves category

**What changed:** Added a narrow bridge between deterministic FX normalization
and category partitioning. Currency conversion changes a transaction's unit and
amount only. A normalized foreign-currency row that directly describes
servicing, maintenance, repair, or process regeneration of an operating asset
or process remains direct Operating Expense evidence; it does not require a
separate auditor reclassification merely because it is denominated in another
currency. Explicit utility, telecom, payroll, rent, marketing, tax, insurance,
interest, and capital categories remain outside this exception.

**Why:** In the combined candidate, the FX stage correctly normalized the sole
foreign operating-service row, but the category policy then excluded that row
in nine of ten runs as a narrower service category. The resulting arithmetic
was internally consistent but omitted a relevant cost and changed both EBITDA
and the verdict. The one correct run used the normalized amount while retaining
the original direct operating-service category.

**Expected result:** Normalization and category classification become
orthogonal: the FX stage supplies the amount, while the source description
continues to supply the category. This refinement is locally tested but still
requires stability measurement before merge.

### Experiment refinement — formula topology, not global disjointness

**What changed:** Narrowed the category-partition policy after its first 10-run
stability result. Only additive base categories that truly compete are now
required to be disjoint. The policy separately models numerator subsets,
signed EBITDA adjustment bridges, and covenant-specific relationship/status
predicates. It also states that broad accounting buckets do not automatically
absorb narrower expense rows without formula-specific or final-audit evidence.

**Why:** The first policy made personnel coverage and overhead calculations
stable, but its global disjointness language caused four new failure modes: it
rolled utility and telecom rows into a generic operating-expense bucket; it
removed auditor-scheduled expenses from the base before adding qualifying
items back; it excluded a restricted asset transfer from a total-CapEx
denominator; and it inferred related-party status from an independent
subsidiary-status schedule.

**Result:** The original experiment improved clean mean score from 0.9649 to
0.9734 and made the two target cells perfect in all 10 runs, but the four new
flaky cells show that the first wording is unsafe to merge. This refinement is
covered by prompt-regression tests and still requires a new paid stability run.

### Experiment — evidence-backed, disjoint category partitions

**What changed:** Replaced the ambiguous personnel-category exception with a
general evidence hierarchy. Transactions retain their explicit primary ledger
category unless the governing definition names that category or a final audit
document supplies a row-specific classification. The solver must build
mutually exclusive transaction buckets and check for duplicate transaction IDs
before calculating; named numerator or overhead rows cannot also enter
Operating Expenses or EBITDA unless the formula explicitly requires overlap.
Compliant decisions now always return a null evidence transaction.

**Why:** Repeated public runs produced several internally consistent answers
from the same inputs solely because the model sometimes treated social tax,
insurance, or travel as personnel expense. A separate flaky calculation also
counted a named category in both its direct bucket and Operating Expenses. In
both cases the arithmetic was correct for an unstable transaction partition.

**Expected result:** Category membership becomes traceable to source evidence,
personnel and competing primary categories no longer overlap by inference, and
each transaction contributes at most once to a formula unless overlap is
expressly required. This branch has no paid-API result yet; it must beat the
recorded stability baseline without regressing previously stable cells before
merge.

### experiment/ocr-router-v3 — displayed-geometry selective vision

**What changed:** Replaced the primary intrinsic-pixel heuristic with visible
page-area analysis from `pdftohtml -xml`. A page is routed when one displayed
image covers at least 2% of the page or the union of image tiles covers at
least 3%. The old `pdfimages` heuristic remains a fallback. Routing reasons,
coverage, original PDF page numbers, and output image provenance are logged.

**Why:** Intrinsic dimensions do not say how large an image appears. A low-DPI
table may occupy 40% of a text-rich page while falling below the old 150,000
pixel threshold; a high-resolution logo can create the opposite false alarm.

**Result:** The public corpus still routes the same six genuine raster pages
plus one sparse native-text page. Adversarial tests cover low-resolution large
rasters, tiled scans, OCR text layers, and small-logo exclusion. No paid API
evaluation was run on this isolated experiment branch.

**Tradeoff:** Vector-only graphics, PDF annotations, and very small raster
stamps below 2% remain outside the automatic geometry gate. Decisive source
documents should still receive a final visual verification pass.

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
