# Evaluation artifacts

This directory contains the small, sanitized portion of the evaluation record
that is safe and useful to publish. `public-final-summary.json` is
machine-readable and records final public smoke/stability metrics, aggregate
private stability counts, token usage, timings, and SHA-256 hashes of the
corresponding full local artifacts.

Full `runs/` artifacts are intentionally excluded from Git. They total hundreds
of megabytes and contain challenge PDFs, extracted private evidence, exact
prompts, complete provider responses, and private answer candidates. Publishing
them would redistribute the dataset and leak private evaluation content. API
credentials are redacted by the logger, but that does not make document and
answer contents suitable for publication.

The public metrics can be reproduced using the commands in the root README.
