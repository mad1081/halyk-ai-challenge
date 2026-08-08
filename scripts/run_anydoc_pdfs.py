#!/usr/bin/env python3
"""Convert a deterministic subset of a PDF directory to Markdown with AnyDoc.

Examples:
    python scripts/run_anydoc_pdfs.py 10
    python scripts/run_anydoc_pdfs.py -1
    python scripts/run_anydoc_pdfs.py 25 --timeout 120

Each PDF is converted in a fresh subprocess. This prevents a parser crash or
timeout in one document from terminating the entire batch runner.
"""

from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone


WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = WORKSPACE / "agentic-bank-public" / "documents"
DEFAULT_OUTPUT_DIR = WORKSPACE / "anydoc-results"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def worker(input_path: Path, output_path: Path) -> int:
    """Convert exactly one PDF; invoked only in an isolated child process."""
    try:
        import anydoc

        markdown = anydoc.to_markdown(str(input_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
        temporary.write_text(markdown, encoding="utf-8", newline="\n")
        os.replace(temporary, output_path)
        return 0
    except BaseException as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert PDFs to Markdown with AnyDoc. COUNT=-1 processes all PDFs; "
            "a positive COUNT processes that many files in filename order."
        )
    )
    parser.add_argument("count", type=int, help="-1 for all PDFs, or a positive file count")
    parser.add_argument(
        "--input-dir", type=Path, default=DEFAULT_INPUT_DIR, help="directory containing PDFs"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Markdown/results directory"
    )
    parser.add_argument(
        "--timeout", type=float, default=60.0, help="maximum seconds per PDF (default: 60)"
    )
    args = parser.parse_args()
    if args.count == 0 or args.count < -1:
        parser.error("COUNT must be -1 or a positive integer")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    return args


def write_reports(output_dir: Path, report: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "run-summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output_dir / "run-summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["index", "input", "output", "status", "seconds", "output_bytes", "error"],
        )
        writer.writeheader()
        writer.writerows(report["files"])


def main() -> int:
    # Private child-process protocol; not exposed as a normal CLI option.
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        return worker(Path(sys.argv[2]), Path(sys.argv[3]))

    args = parse_args()
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    if not input_dir.is_dir():
        print(f"Input directory does not exist: {input_dir}", file=sys.stderr)
        return 2

    pdfs = sorted(
        (path for path in input_dir.iterdir() if path.is_file() and path.suffix.lower() == ".pdf"),
        key=lambda path: (path.name.casefold(), path.name),
    )
    selected = pdfs if args.count == -1 else pdfs[: args.count]
    if not selected:
        print(f"No PDF files found in: {input_dir}", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = utc_now()
    results: list[dict] = []

    for index, input_path in enumerate(selected, start=1):
        output_path = output_dir / f"{input_path.stem}.md"
        # Never let an output from an earlier run masquerade as this run's result.
        output_path.unlink(missing_ok=True)
        start = time.perf_counter()
        status = "success"
        error = ""
        try:
            completed = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker", str(input_path), str(output_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=args.timeout,
                check=False,
            )
            if completed.returncode != 0:
                status = "error"
                error = (completed.stderr or completed.stdout or f"exit code {completed.returncode}").strip()
        except subprocess.TimeoutExpired:
            status = "timeout"
            error = f"exceeded {args.timeout:g}-second timeout"

        elapsed = round(time.perf_counter() - start, 4)
        output_bytes = output_path.stat().st_size if status == "success" and output_path.exists() else 0
        result = {
            "index": index,
            "input": str(input_path),
            "output": str(output_path) if status == "success" else "",
            "status": status,
            "seconds": elapsed,
            "output_bytes": output_bytes,
            "error": error,
        }
        results.append(result)
        print(f"[{index}/{len(selected)}] {status:7} {input_path.name} ({elapsed:.3f}s)")

    report = {
        "tool": "firecrawl-anydoc",
        "tool_version": importlib.metadata.version("firecrawl-anydoc"),
        "started_at": started_at,
        "finished_at": utc_now(),
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "requested_count": args.count,
        "available_pdf_count": len(pdfs),
        "selected_pdf_count": len(selected),
        "timeout_seconds": args.timeout,
        "success_count": sum(item["status"] == "success" for item in results),
        "failure_count": sum(item["status"] != "success" for item in results),
        "files": results,
    }
    write_reports(output_dir, report)
    print(
        f"Finished: {report['success_count']} succeeded, {report['failure_count']} failed. "
        f"Reports: {output_dir / 'run-summary.json'}"
    )
    return 1 if report["failure_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
