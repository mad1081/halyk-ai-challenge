from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Protocol

from halyk_agent.extraction.quality import assess_text_quality
from halyk_agent.models import ExtractedDocument, ExtractionAttempt


class ExtractionBackend(Protocol):
    name: str

    def available(self) -> bool: ...

    def extract(self, pdf_path: Path, timeout: float) -> str: ...


@dataclass(slots=True)
class AnyDocExtractor:
    python_executable: Path = Path(sys.executable)
    name: str = "anydoc"

    def available(self) -> bool:
        return self.python_executable.is_file() or shutil.which(str(self.python_executable)) is not None

    def extract(self, pdf_path: Path, timeout: float) -> str:
        with tempfile.TemporaryDirectory(prefix="halyk-anydoc-") as temporary:
            output = Path(temporary) / "output.md"
            source_dir = Path(__file__).resolve().parents[2]
            environment = os.environ.copy()
            existing_pythonpath = environment.get("PYTHONPATH")
            environment["PYTHONPATH"] = (
                str(source_dir)
                if not existing_pythonpath
                else str(source_dir) + os.pathsep + existing_pythonpath
            )
            completed = subprocess.run(
                [
                    str(self.python_executable),
                    "-m",
                    "halyk_agent.extraction.anydoc_worker",
                    str(pdf_path),
                    str(output),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                env=environment,
            )
            if completed.returncode != 0:
                message = (completed.stderr or completed.stdout).strip()
                raise RuntimeError(message or f"AnyDoc exited with {completed.returncode}")
            return output.read_text(encoding="utf-8")


@dataclass(slots=True)
class PdfToTextExtractor:
    executable: str = "pdftotext"
    name: str = "pdftotext"

    def available(self) -> bool:
        return shutil.which(self.executable) is not None

    def extract(self, pdf_path: Path, timeout: float) -> str:
        with tempfile.TemporaryDirectory(prefix="halyk-pdftotext-") as temporary:
            output = Path(temporary) / "output.txt"
            completed = subprocess.run(
                [self.executable, "-layout", "-enc", "UTF-8", str(pdf_path), str(output)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    (completed.stderr or completed.stdout).strip()
                    or f"pdftotext exited with {completed.returncode}"
                )
            return output.read_text(encoding="utf-8", errors="replace")


@dataclass(slots=True)
class OcrMyPdfExtractor:
    ocrmypdf_executable: str = "ocrmypdf"
    pdftotext_executable: str = "pdftotext"
    languages: str = "rus+kaz+eng"
    name: str = "ocrmypdf"

    def available(self) -> bool:
        return (
            shutil.which(self.ocrmypdf_executable) is not None
            and shutil.which(self.pdftotext_executable) is not None
        )

    def extract(self, pdf_path: Path, timeout: float) -> str:
        with tempfile.TemporaryDirectory(prefix="halyk-ocr-") as temporary:
            searchable_pdf = Path(temporary) / "searchable.pdf"
            output_text = Path(temporary) / "output.txt"
            completed = subprocess.run(
                [
                    self.ocrmypdf_executable,
                    "--skip-text",
                    "--deskew",
                    "--rotate-pages",
                    "--language",
                    self.languages,
                    str(pdf_path),
                    str(searchable_pdf),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    (completed.stderr or completed.stdout).strip()
                    or f"ocrmypdf exited with {completed.returncode}"
                )
            completed = subprocess.run(
                [
                    self.pdftotext_executable,
                    "-layout",
                    "-enc",
                    "UTF-8",
                    str(searchable_pdf),
                    str(output_text),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError("pdftotext failed after OCR")
            return output_text.read_text(encoding="utf-8", errors="replace")


class CascadeExtractor:
    def __init__(self, backends: list[ExtractionBackend]):
        self.backends = backends

    def extract(self, pdf_path: Path, timeout: float = 90.0) -> ExtractedDocument:
        attempts: list[ExtractionAttempt] = []
        candidates: list[tuple[str, str, object]] = []
        for backend in self.backends:
            if not backend.available():
                attempts.append(ExtractionAttempt(backend.name, "unavailable", 0.0))
                continue
            started = time.perf_counter()
            try:
                markdown = backend.extract(pdf_path, timeout)
                quality = assess_text_quality(markdown)
                elapsed = round(time.perf_counter() - started, 4)
                attempts.append(
                    ExtractionAttempt(backend.name, "success", elapsed, quality=quality)
                )
                candidates.append((backend.name, markdown, quality))
                if quality.passed:
                    return ExtractedDocument(
                        pdf_path,
                        markdown,
                        backend.name,
                        quality,
                        tuple(attempts),
                    )
            except subprocess.TimeoutExpired:
                elapsed = round(time.perf_counter() - started, 4)
                attempts.append(
                    ExtractionAttempt(backend.name, "timeout", elapsed, error=f"> {timeout}s")
                )
            except Exception as exc:
                elapsed = round(time.perf_counter() - started, 4)
                attempts.append(
                    ExtractionAttempt(backend.name, "error", elapsed, error=str(exc)[:1000])
                )

        if candidates:
            backend_name, markdown, quality = max(candidates, key=lambda item: item[2].score)
            return ExtractedDocument(
                pdf_path, markdown, backend_name, quality, tuple(attempts)
            )
        errors = "; ".join(
            f"{attempt.backend}: {attempt.status} {attempt.error}" for attempt in attempts
        )
        raise RuntimeError(f"No extractor produced output for {pdf_path.name}: {errors}")

