from __future__ import annotations

import json
from pathlib import Path
import re

from halyk_agent.dataset import DatasetLayout
from halyk_agent.extraction.backends import CascadeExtractor


ACCOUNT_PATTERN = re.compile(r"\bACC-\d+(?:-\d+)?\b", re.IGNORECASE)


def extract_documents(
    layout: DatasetLayout,
    output_dir: Path,
    extractor: CascadeExtractor,
    *,
    limit: int | None,
    timeout: float,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    pdfs = layout.pdf_paths if limit is None else layout.pdf_paths[:limit]
    records: list[dict] = []
    for index, pdf_path in enumerate(pdfs, start=1):
        try:
            result = extractor.extract(pdf_path, timeout=timeout)
            output_path = output_dir / f"{pdf_path.stem}.md"
            temporary = output_path.with_name(f".{output_path.name}.tmp")
            temporary.write_text(result.markdown, encoding="utf-8", newline="\n")
            temporary.replace(output_path)
            record = {
                "index": index,
                "source": str(pdf_path),
                "output": str(output_path),
                "status": "success" if result.quality.passed else "low_quality",
                "selected_backend": result.selected_backend,
                "quality": result.quality.to_dict(),
                "account_ids": sorted(set(ACCOUNT_PATTERN.findall(result.markdown))),
                "attempts": [attempt.to_dict() for attempt in result.attempts],
            }
        except Exception as exc:
            record = {
                "index": index,
                "source": str(pdf_path),
                "output": None,
                "status": "error",
                "error": str(exc),
            }
        records.append(record)
        print(f"[{index}/{len(pdfs)}] {record['status']:11} {pdf_path.name}")

    manifest = {
        "pdf_count": len(pdfs),
        "success_count": sum(row["status"] == "success" for row in records),
        "low_quality_count": sum(row["status"] == "low_quality" for row in records),
        "error_count": sum(row["status"] == "error" for row in records),
        "documents": records,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest

