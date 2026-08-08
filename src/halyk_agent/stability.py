from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean, median, pstdev
import time
from typing import Any

from halyk_agent.benchmark import (
    BenchmarkError,
    DocumentCatalog,
    SYSTEM_PROMPT,
    _add_usage,
    _apply_decisions,
    _build_user_prompt,
    _execute_scenario,
    _ocr_images,
    benchmark_schema,
)
from halyk_agent.dataset import dataset_fingerprint, materialize_dataset
from halyk_agent.evaluation import evaluate_submission
from halyk_agent.ledger import LedgerIndex
from halyk_agent.llm import LlmSettings, build_provider
from halyk_agent.llm.transport import UrllibJsonTransport
from halyk_agent.runlog import JsonlRunLogger, RecordingTransport


def run_stability_benchmark(
    *,
    dataset: Path,
    documents_dir: Path,
    output_dir: Path,
    providers: tuple[str, ...],
    env_file: Path,
    scan_images_dir: Path | None = None,
    repetitions: int = 10,
    retries: int = 2,
    concurrency: int = 35,
    excluded_cells: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Run repeated independent solver passes with one shared OCR per provider."""

    if repetitions <= 0:
        raise ValueError("repetitions must be positive")
    if retries < 0:
        raise ValueError("retries must be zero or positive")
    if concurrency <= 0:
        raise ValueError("concurrency must be positive")
    exclusions = _parse_excluded_cells(excluded_cells)

    benchmark_started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    root_logger = JsonlRunLogger(output_dir)
    root_logger.event(
        "stability_benchmark_started",
        dataset=str(dataset.resolve()),
        documents_dir=str(documents_dir.resolve()),
        providers=list(providers),
        repetitions=repetitions,
        concurrency_per_provider=concurrency,
        retries=retries,
        excluded_cells=sorted(f"{s}/{c}" for s, c in exclusions),
    )

    layout = materialize_dataset(dataset, output_dir / "work")
    if layout.ground_truth_path is None:
        raise BenchmarkError("Stability benchmark requires public ground_truth.json")
    template = layout.load_template()
    scenarios = tuple(template["answers"].keys())
    ledger = LedgerIndex.from_csv(layout.ledger_path)
    accounts = ledger.scenario_accounts(scenarios)
    catalog = DocumentCatalog.from_directory(documents_dir)
    image_paths: tuple[Path, ...] = ()
    if scan_images_dir is not None:
        image_paths = tuple(
            sorted(scan_images_dir.glob("*.png"), key=lambda path: path.name.casefold())
        )
        if not image_paths:
            raise BenchmarkError(f"No PNG pages found in {scan_images_dir}")

    dataset_summary = {
        "dataset_fingerprint": dataset_fingerprint(layout),
        "scenario_count": len(scenarios),
        "catalog_document_count": len(catalog.records),
        "scan_page_count": len(image_paths),
        "accounts": accounts,
    }
    root_logger.artifact("dataset.json", dataset_summary)

    settings = LlmSettings.from_env(env_file)
    missing = [name for name in providers if name not in settings.providers]
    if missing:
        raise BenchmarkError("Missing credentials for providers: " + ", ".join(missing))

    provider_summaries: dict[str, Any] = {}
    # Providers have independent rate limits and therefore run at the same time.
    with ThreadPoolExecutor(
        max_workers=len(providers), thread_name_prefix="halyk-provider"
    ) as executor:
        futures = {
            executor.submit(
                _run_stability_provider,
                provider_name=provider_name,
                settings=settings,
                output_dir=output_dir / provider_name,
                template=template,
                scenarios=scenarios,
                accounts=accounts,
                ledger=ledger,
                catalog=catalog,
                scan_image_paths=image_paths,
                ground_truth_path=layout.ground_truth_path,
                repetitions=repetitions,
                retries=retries,
                concurrency=concurrency,
                exclusions=exclusions,
            ): provider_name
            for provider_name in providers
        }
        for future in as_completed(futures):
            provider_name = futures[future]
            provider_summaries[provider_name] = future.result()

    elapsed = round(time.perf_counter() - benchmark_started, 4)
    comparison = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": elapsed,
        "elapsed_minutes": round(elapsed / 60, 4),
        "dataset": dataset_summary,
        "repetitions": repetitions,
        "concurrency_per_provider": concurrency,
        "providers": provider_summaries,
    }
    root_logger.artifact("comparison.json", comparison)
    root_logger.event(
        "stability_benchmark_completed",
        elapsed_seconds=elapsed,
        elapsed_minutes=round(elapsed / 60, 4),
        score_means={
            name: summary["score_statistics"]["mean"]
            for name, summary in provider_summaries.items()
        },
    )
    return comparison


def _run_stability_provider(
    *,
    provider_name: str,
    settings: LlmSettings,
    output_dir: Path,
    template: dict[str, Any],
    scenarios: tuple[str, ...],
    accounts: dict[str, str],
    ledger: LedgerIndex,
    catalog: DocumentCatalog,
    scan_image_paths: tuple[Path, ...],
    ground_truth_path: Path,
    repetitions: int,
    retries: int,
    concurrency: int,
    exclusions: set[tuple[str, str]],
) -> dict[str, Any]:
    logger = JsonlRunLogger(output_dir)
    selected_settings = replace(settings, requested_provider=provider_name)
    provider_settings = selected_settings.select()
    started = time.perf_counter()
    usage_totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    logger.event(
        "stability_provider_started",
        provider=provider_name,
        model=provider_settings.model,
        repetitions=repetitions,
        scenario_count=len(scenarios),
        total_solver_tasks=repetitions * len(scenarios),
        concurrency=concurrency,
    )

    provider_catalog = catalog
    ocr_summary: dict[str, Any] | None = None
    if scan_image_paths:
        recording_transport = RecordingTransport(
            UrllibJsonTransport(), logger, provider_name
        )
        client = build_provider(selected_settings, recording_transport)
        ocr_record, ocr_summary = _ocr_images(
            client=client,
            recording_transport=recording_transport,
            logger=logger,
            provider_name=provider_name,
            model=provider_settings.model,
            image_paths=scan_image_paths,
            retries=retries,
        )
        provider_catalog = DocumentCatalog(catalog.records + (ocr_record,))
        _add_usage(usage_totals, ocr_summary["usage"])

    retrieval = {
        scenario: provider_catalog.for_account(accounts[scenario])
        for scenario in scenarios
    }
    missing = [scenario for scenario, records in retrieval.items() if not records]
    if missing:
        raise BenchmarkError(
            f"{provider_name}: no documents matched account_id for scenarios: "
            + ", ".join(missing)
        )
    retrieval_counts = {
        scenario: len(records) for scenario, records in retrieval.items()
    }
    logger.artifact(
        "retrieval.json",
        {
            scenario: {
                "account_id": accounts[scenario],
                "documents": [record.name for record in records],
            }
            for scenario, records in retrieval.items()
        },
    )

    scenario_tasks: list[dict[str, Any]] = []
    for scenario_index, scenario in enumerate(scenarios, start=1):
        covenants = tuple(template["answers"][scenario].keys())
        prompt = _build_user_prompt(
            scenario=scenario,
            account_id=accounts[scenario],
            covenants=covenants,
            records=retrieval[scenario],
            transactions=ledger.by_scenario[scenario],
        )
        logger.artifact(
            Path("prompts") / f"{scenario}.json",
            {
                "scenario": scenario,
                "account_id": accounts[scenario],
                "system_prompt": SYSTEM_PROMPT,
                "user_prompt": prompt,
                "schema": benchmark_schema(covenants),
                "reused_across_repetitions": repetitions,
            },
        )
        scenario_tasks.append(
            {
                "scenario": scenario,
                "scenario_index": scenario_index,
                "covenants": covenants,
                "user_prompt": prompt,
            }
        )

    results: dict[tuple[int, str], dict[str, Any]] = {}
    with ThreadPoolExecutor(
        max_workers=concurrency,
        thread_name_prefix=f"stability-{provider_name}",
    ) as executor:
        futures = {}
        for repetition in range(1, repetitions + 1):
            for task in scenario_tasks:
                queued_at = time.perf_counter()
                key = (repetition, task["scenario"])
                future = executor.submit(
                    _execute_scenario,
                    selected_settings=selected_settings,
                    provider_name=provider_name,
                    model=provider_settings.model,
                    logger=logger,
                    scenario=task["scenario"],
                    scenario_index=task["scenario_index"],
                    covenants=task["covenants"],
                    user_prompt=task["user_prompt"],
                    retries=retries,
                    queued_at=queued_at,
                    repetition=repetition,
                    artifact_directory=(
                        Path("repetitions") / f"{repetition:03d}" / "decisions"
                    ),
                )
                futures[future] = key

        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as exc:
                repetition, scenario = key
                logger.event(
                    "scenario_worker_failed",
                    repetition=repetition,
                    scenario=scenario,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                results[key] = {
                    "scenario": scenario,
                    "repetition": repetition,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "timing": {},
                }

    # The answer key is intentionally opened only after all model calls finish.
    ground_truth = json.loads(ground_truth_path.read_text(encoding="utf-8-sig"))
    evaluations: list[dict[str, Any]] = []
    submissions: list[dict[str, Any]] = []
    repetition_summaries: list[dict[str, Any]] = []
    for repetition in range(1, repetitions + 1):
        submission = _new_submission(template, provider_settings.model, repetition)
        failures = []
        run_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        timings = {}
        for scenario in scenarios:
            outcome = results[(repetition, scenario)]
            timings[scenario] = outcome.get("timing", {})
            if "error" in outcome:
                failures.append(
                    {
                        "scenario": scenario,
                        "error_type": outcome.get("error_type", "BenchmarkError"),
                        "error": outcome["error"],
                    }
                )
                continue
            covenants = tuple(template["answers"][scenario].keys())
            _apply_decisions(submission, scenario, covenants, outcome["decisions"])
            _add_usage(run_usage, outcome["usage"])
            _add_usage(usage_totals, outcome["usage"])

        evaluation = evaluate_submission(submission, ground_truth)
        run_dir = Path("repetitions") / f"{repetition:03d}"
        submission_path = logger.artifact(run_dir / "submission.json", submission)
        evaluation_path = logger.artifact(run_dir / "evaluation.json", evaluation)
        clean_score = _score_excluding(evaluation["cells"], exclusions)
        run_summary = {
            "repetition": repetition,
            "proxy_score": evaluation["proxy_score"],
            "clean_proxy_score": clean_score,
            "status_accuracy": evaluation["status_accuracy"],
            "perfect_cell_count": evaluation["perfect_cell_count"],
            "failure_count": len(failures),
            "failures": failures,
            "usage": run_usage,
            "scenario_timings": timings,
            "artifacts": {
                "submission": str(submission_path.relative_to(logger.run_dir)),
                "evaluation": str(evaluation_path.relative_to(logger.run_dir)),
            },
        }
        logger.artifact(run_dir / "summary.json", run_summary)
        evaluations.append(evaluation)
        submissions.append(submission)
        repetition_summaries.append(run_summary)

    stability = aggregate_stability(
        evaluations=evaluations,
        submissions=submissions,
        repetitions=repetitions,
        exclusions=exclusions,
    )
    stability_path = logger.artifact("stability.json", stability)
    repetitions_path = logger.artifact("repetitions.json", repetition_summaries)
    elapsed = round(time.perf_counter() - started, 4)
    summary = {
        "provider": provider_name,
        "model": provider_settings.model,
        "elapsed_seconds": elapsed,
        "elapsed_minutes": round(elapsed / 60, 4),
        "repetitions": repetitions,
        "concurrency": concurrency,
        "scenario_count": len(scenarios),
        "total_solver_tasks": repetitions * len(scenarios),
        "completed_solver_tasks": sum("error" not in value for value in results.values()),
        "usage": usage_totals,
        "ocr": ocr_summary,
        "retrieved_document_counts": retrieval_counts,
        "score_statistics": stability["score_statistics"],
        "clean_score_statistics": stability["clean_score_statistics"],
        "artifacts": {
            "events": "events.jsonl",
            "stability": str(stability_path.relative_to(logger.run_dir)),
            "repetitions": str(repetitions_path.relative_to(logger.run_dir)),
        },
    }
    logger.artifact("summary.json", summary)
    logger.event(
        "stability_provider_completed",
        elapsed_seconds=elapsed,
        elapsed_minutes=round(elapsed / 60, 4),
        completed_solver_tasks=summary["completed_solver_tasks"],
        total_solver_tasks=summary["total_solver_tasks"],
        score_statistics=summary["score_statistics"],
        usage=usage_totals,
    )
    return summary


def aggregate_stability(
    *,
    evaluations: list[dict[str, Any]],
    submissions: list[dict[str, Any]],
    repetitions: int,
    exclusions: set[tuple[str, str]],
) -> dict[str, Any]:
    if len(evaluations) != repetitions or len(submissions) != repetitions:
        raise ValueError("evaluation and submission counts must equal repetitions")

    proxy_scores = [float(evaluation["proxy_score"]) for evaluation in evaluations]
    clean_scores = [
        _score_excluding(evaluation["cells"], exclusions)
        for evaluation in evaluations
    ]
    cells: dict[str, dict[str, Any]] = {}
    first_cells = evaluations[0]["cells"]
    for cell_index, first in enumerate(first_cells):
        scenario = str(first["scenario"])
        covenant = str(first["covenant"])
        key = f"{scenario}/{covenant}"
        scores = [evaluation["cells"][cell_index] for evaluation in evaluations]
        candidates = [
            submission["answers"][scenario][covenant] for submission in submissions
        ]
        distribution: dict[str, int] = {}
        for candidate in candidates:
            label = json.dumps(candidate, ensure_ascii=False, sort_keys=True)
            distribution[label] = distribution.get(label, 0) + 1
        totals = [float(score["total"]) for score in scores]
        perfect_count = sum(total == 1.0 for total in totals)
        cells[key] = {
            "scenario": scenario,
            "covenant": covenant,
            "excluded_known_issue": (scenario, covenant) in exclusions,
            "status_correct_count": sum(
                float(score["status_score"]) == 0.5 for score in scores
            ),
            "actual_exact_count": sum(
                float(score["actual_score"]) == 0.3 for score in scores
            ),
            "perfect_count": perfect_count,
            "perfect_rate": round(perfect_count / repetitions, 4),
            "mean_cell_score": round(mean(totals), 6),
            "min_cell_score": min(totals),
            "max_cell_score": max(totals),
            "stable_failure": perfect_count == 0,
            "flaky": 0 < perfect_count < repetitions,
            "candidate_distribution": [
                {"count": count, "answer": json.loads(label)}
                for label, count in sorted(
                    distribution.items(), key=lambda item: (-item[1], item[0])
                )
            ],
        }

    return {
        "repetitions": repetitions,
        "excluded_cells": sorted(f"{s}/{c}" for s, c in exclusions),
        "score_statistics": _statistics(proxy_scores),
        "clean_score_statistics": _statistics(clean_scores),
        "stable_failure_cells": [
            key
            for key, cell in cells.items()
            if cell["stable_failure"] and not cell["excluded_known_issue"]
        ],
        "flaky_cells": [key for key, cell in cells.items() if cell["flaky"]],
        "cells": cells,
    }


def _statistics(values: list[float]) -> dict[str, float]:
    return {
        "mean": round(mean(values), 6),
        "median": round(median(values), 6),
        "stddev": round(pstdev(values), 6),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
    }


def _score_excluding(
    cells: list[dict[str, Any]], exclusions: set[tuple[str, str]]
) -> float:
    included = [
        float(cell["total"])
        for cell in cells
        if (str(cell["scenario"]), str(cell["covenant"])) not in exclusions
    ]
    return round(mean(included), 12) if included else 0.0


def _parse_excluded_cells(values: tuple[str, ...]) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for value in values:
        if "/" not in value:
            raise ValueError("excluded cells must use SCENARIO/COVENANT, for example P4/6.3")
        scenario, covenant = (part.strip() for part in value.split("/", 1))
        if not scenario or not covenant:
            raise ValueError("excluded cells must use SCENARIO/COVENANT")
        result.add((scenario, covenant))
    return result


def _new_submission(
    template: dict[str, Any], model: str, repetition: int
) -> dict[str, Any]:
    submission = json.loads(json.dumps(template))
    submission["team"] = "stability-eval"
    submission["contact_email"] = "eval@local.invalid"
    submission["model"] = model
    return submission
