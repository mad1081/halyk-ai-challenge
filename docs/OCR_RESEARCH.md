# PDF and OCR research

Research date: 2026-08-08.

## Recommendation

Do not make AnyDoc the only parser. Use a tiered path:

```text
AnyDoc (MVP) / direct current pdf-inspector (target)
  -> per-document and later per-page quality gate
  -> Docling standard pipeline + RapidOCR Cyrillic
  -> OCRmyPDF emergency local fallback
  -> optional Firecrawl Parse OCR or vision API fallback
```

This keeps the common text-native path fast while still handling real scans,
mixed PDFs and tables during the three-hour private round.

## AnyDoc findings

- The existing experiment converted the first 10 public PDFs successfully.
- AnyDoc delegates PDF work to `pdf-inspector`; it does not OCR image-only
  PDFs.
- AnyDoc 0.1.6 locks `lopdf` 0.41.0, affected by a high-severity stack-overflow
  denial of service. The fix is `lopdf >= 0.42.0`.
- It is acceptable for the trusted challenge corpus only behind a child process
  and per-file timeout. It should not parse arbitrary public uploads.

The current `pdf-inspector` source is a better future PDF-specific Tier 0: it
classifies text/scanned/mixed/image PDFs, reports `pages_needing_ocr`, preserves
page boundaries, supports tables, and already uses `lopdf` 0.42.0. Its current
Python path requires a Rust/maturin build, so the MVP retains AnyDoc while that
adapter is evaluated.

Primary sources:

- [AnyDoc](https://github.com/firecrawl/anydoc)
- [pdf-inspector](https://github.com/firecrawl/pdf-inspector)
- [RUSTSEC-2026-0187](https://rustsec.org/advisories/RUSTSEC-2026-0187.html)

## Local OCR choice

Docling standard pipeline with RapidOCR/PP-OCRv5 Cyrillic is the preferred
local fallback because it supports Windows, local inference, document layout,
reading order and tables. The Cyrillic model covers Russian, Kazakh and English.
Export both Markdown for the model and JSON for page/block provenance.

For mixed PDFs prefer `pdf_aware_layout_regions`; use `full_page` for a known
image-only scan. Models must be downloaded before the private round and tested
fully offline.

Primary sources:

- [Docling](https://github.com/docling-project/docling)
- [Docling OCR engines](https://docling-project.github.io/docling/concepts/OCR/)

## Cloud fallback

Firecrawl Parse `/v2/parse` offers `fast`, `auto` and `ocr` PDF modes. It is a
convenient last resort, not a mandatory dependency: files leave the machine,
an API key/network are required, and the service has file/plan constraints.

- [Firecrawl Parse](https://docs.firecrawl.dev/features/parse)

## Quality gate

Parser exit code and non-empty output are insufficient. Trigger a fallback on:

- timeout, unsupported/encrypted document or parser error;
- fewer than 200 document characters in the MVP;
- fewer than 30-50 alphanumeric characters on a visually populated page;
- replacement-character ratio above 0.5%;
- printable-character ratio below 85%;
- missing pages or pages reported by `pages_needing_ocr`;
- missing tables on pages known to contain tables;
- material disagreement between native extractors.

Finance-specific integrity checks should compare preservation of:

```text
ACC-\d{4}
TXN-[A-Z0-9-]+
USD|EUR|KZT|₸|\$|%
6\.[123]
dates and decimal amounts
```

If extractors disagree on identifiers or financial numbers, retain both
outputs and route the document to the stronger parser rather than accepting
the longest text blindly.

## Alternatives

- **OCRmyPDF + Tesseract:** reliable searchable-PDF fallback, weaker document
  structure; MPL-2.0 / Apache-2.0.
- **Marker:** strong GPU experiment candidate; heavier runtime and separate
  model-weight terms.
- **PyMuPDF/PyMuPDF4LLM:** capable and fast, but AGPL/commercial licensing must
  be acceptable for the project.
- **pdftotext:** useful independent baseline, no OCR and limited structure.

