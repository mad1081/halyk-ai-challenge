from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from halyk_agent.benchmark import BenchmarkError, run_live_benchmark
from halyk_agent.dataset import DatasetError, dataset_fingerprint, materialize_dataset
from halyk_agent.evaluation import evaluate_submission
from halyk_agent.extraction.backends import (
    AnyDocExtractor,
    CascadeExtractor,
    DoclingExtractor,
    OcrMyPdfExtractor,
    PdfToTextExtractor,
)
from halyk_agent.extraction.pipeline import extract_documents
from halyk_agent.ledger import LedgerError, LedgerIndex
from halyk_agent.llm import LlmConfigurationError, LlmSettings
from halyk_agent.submission import create_draft, write_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="halyk-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="validate and summarize a dataset")
    inspect_parser.add_argument("dataset", type=Path)
    inspect_parser.add_argument("--work-dir", type=Path, default=Path("work"))

    mvp_parser = subparsers.add_parser("mvp", help="prepare deterministic MVP run artifacts")
    mvp_parser.add_argument("dataset", type=Path)
    mvp_parser.add_argument("--work-dir", type=Path, required=True)
    mvp_parser.add_argument("--team", default="")
    mvp_parser.add_argument("--contact-email", default="")
    mvp_parser.add_argument("--model", default="unconfigured")

    extract_parser = subparsers.add_parser("extract", help="extract dataset PDFs to Markdown")
    extract_parser.add_argument("dataset", type=Path)
    extract_parser.add_argument("--output-dir", type=Path, required=True)
    extract_parser.add_argument("--work-dir", type=Path, default=Path("work"))
    extract_parser.add_argument("--limit", type=int)
    extract_parser.add_argument("--timeout", type=float, default=90.0)
    extract_parser.add_argument("--anydoc-python", type=Path)
    extract_parser.add_argument("--no-anydoc", action="store_true")
    extract_parser.add_argument("--no-docling", action="store_true")
    extract_parser.add_argument("--docling-command", default="docling")
    extract_parser.add_argument("--no-ocr", action="store_true")

    eval_parser = subparsers.add_parser("evaluate", help="score a submission on public truth")
    eval_parser.add_argument("submission", type=Path)
    eval_parser.add_argument("ground_truth", type=Path)
    eval_parser.add_argument("--details", type=Path)

    llm_parser = subparsers.add_parser(
        "llm-status", help="show the selected LLM provider without calling its API"
    )
    llm_parser.add_argument("--env-file", type=Path, default=Path(".env"))

    benchmark_parser = subparsers.add_parser(
        "live-eval", help="run the covenant agent and score both live LLM providers"
    )
    benchmark_parser.add_argument("dataset", type=Path)
    benchmark_parser.add_argument("--documents-dir", type=Path, required=True)
    benchmark_parser.add_argument("--scan-images-dir", type=Path)
    benchmark_parser.add_argument("--output-dir", type=Path, required=True)
    benchmark_parser.add_argument("--env-file", type=Path, default=Path(".env"))
    benchmark_parser.add_argument(
        "--providers",
        nargs="+",
        choices=("openai", "anthropic"),
        default=("openai", "anthropic"),
    )
    benchmark_parser.add_argument("--retries", type=int, default=1)
    benchmark_parser.add_argument(
        "--concurrency",
        type=int,
        default=7,
        help="number of scenario requests to run concurrently (default: 7)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inspect":
            return _inspect(args)
        if args.command == "mvp":
            return _mvp(args)
        if args.command == "extract":
            return _extract(args)
        if args.command == "evaluate":
            return _evaluate(args)
        if args.command == "llm-status":
            return _llm_status(args)
        if args.command == "live-eval":
            return _live_eval(args)
    except (
        BenchmarkError,
        DatasetError,
        LedgerError,
        LlmConfigurationError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


def _load_context(dataset: Path, work_dir: Path):
    layout = materialize_dataset(dataset, work_dir)
    template = layout.load_template()
    scenarios = tuple(template["answers"].keys())
    ledger = LedgerIndex.from_csv(layout.ledger_path)
    accounts = ledger.scenario_accounts(scenarios)
    return layout, template, scenarios, ledger, accounts


def _summary(layout, scenarios, ledger, accounts) -> dict:
    return {
        "dataset_root": str(layout.root),
        "dataset_fingerprint": dataset_fingerprint(layout),
        "pdf_count": len(layout.pdf_paths),
        "has_ground_truth": layout.ground_truth_path is not None,
        "target_scenarios": list(scenarios),
        "scenario_accounts": accounts,
        "ledger": ledger.summary(scenarios),
    }


def _inspect(args) -> int:
    layout, _, scenarios, ledger, accounts = _load_context(args.dataset, args.work_dir)
    print(json.dumps(_summary(layout, scenarios, ledger, accounts), ensure_ascii=False, indent=2))
    return 0


def _mvp(args) -> int:
    layout, template, scenarios, ledger, accounts = _load_context(args.dataset, args.work_dir)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.work_dir / "dataset-summary.json", _summary(layout, scenarios, ledger, accounts))
    write_json(args.work_dir / "scenario-accounts.json", accounts)
    draft = create_draft(
        template,
        team=args.team,
        contact_email=args.contact_email,
        model=args.model,
    )
    write_json(args.work_dir / "submission.draft.json", draft)
    print(f"Prepared MVP run directory: {args.work_dir.resolve()}")
    print("Draft answers remain null until the covenant solver is configured.")
    return 0


def _extract(args) -> int:
    if args.limit is not None and args.limit <= 0:
        raise ValueError("--limit must be positive when supplied")
    layout = materialize_dataset(args.dataset, args.work_dir)
    backends = []
    if not args.no_anydoc:
        executable = args.anydoc_python or Path(sys.executable)
        backends.append(AnyDocExtractor(executable))
    backends.append(PdfToTextExtractor())
    if not args.no_docling:
        backends.append(DoclingExtractor(args.docling_command))
    if not args.no_ocr:
        backends.append(OcrMyPdfExtractor())
    manifest = extract_documents(
        layout,
        args.output_dir,
        CascadeExtractor(backends),
        limit=args.limit,
        timeout=args.timeout,
    )
    print(json.dumps({key: value for key, value in manifest.items() if key != "documents"}, indent=2))
    return 1 if manifest["error_count"] else 0


def _evaluate(args) -> int:
    candidate = json.loads(args.submission.read_text(encoding="utf-8-sig"))
    ground_truth = json.loads(args.ground_truth.read_text(encoding="utf-8-sig"))
    result = evaluate_submission(candidate, ground_truth)
    summary = {key: value for key, value in result.items() if key != "cells"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.details:
        write_json(args.details, result)
    return 0


def _llm_status(args) -> int:
    settings = LlmSettings.from_env(args.env_file)
    print(json.dumps(settings.public_summary(), ensure_ascii=False, indent=2))
    return 0


def _live_eval(args) -> int:
    comparison = run_live_benchmark(
        dataset=args.dataset,
        documents_dir=args.documents_dir,
        output_dir=args.output_dir,
        providers=tuple(args.providers),
        env_file=args.env_file,
        scan_images_dir=args.scan_images_dir,
        retries=args.retries,
        concurrency=args.concurrency,
    )
    output = {
        name: {
            "model": summary["model"],
            "elapsed_seconds": summary["elapsed_seconds"],
            "elapsed_minutes": summary["elapsed_minutes"],
            "concurrency": summary["concurrency"],
            "usage": summary["usage"],
            "evaluation": summary["evaluation"],
        }
        for name, summary in comparison["providers"].items()
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
