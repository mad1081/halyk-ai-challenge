from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

from halyk_agent.dataset import DatasetLayout
from halyk_agent.extraction.backends import CascadeExtractor


ACCOUNT_PATTERN = re.compile(r"\bACC-\d+(?:-\d+)?\b", re.IGNORECASE)
PAGES_PATTERN = re.compile(r"^Pages:\s+(\d+)\s*$", re.IGNORECASE | re.MULTILINE)


def _low_text_page_numbers(page_texts: tuple[str, ...]) -> tuple[int, ...]:
    """Return 1-based pages whose native text layer is effectively absent."""

    low_text = []
    for page_number, text in enumerate(page_texts, start=1):
        stripped = text.strip()
        alphanumeric = sum(character.isalnum() for character in stripped)
        if len(stripped) < 80 or alphanumeric < 40:
            low_text.append(page_number)
    return tuple(low_text)


def _parse_pdfimages_pages(output: str) -> tuple[int, ...]:
    """Flag pages containing a substantial raster region.

    This complements blank-page detection for hybrid pages that contain plenty
    of native text plus a scanned table, stamp, signature, or embedded exhibit.
    Tiny icons and logos are ignored to avoid unnecessary vision calls.
    """

    pages = set()
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 6 or not fields[0].isdigit() or fields[2] != "image":
            continue
        try:
            page_number = int(fields[0])
            width = int(fields[3])
            height = int(fields[4])
        except ValueError:
            continue
        pixels = width * height
        if pixels >= 150_000 or (width >= 800 and height >= 150) or (
            height >= 800 and width >= 150
        ):
            pages.add(page_number)
    return tuple(sorted(pages))


def _embedded_image_page_numbers(
    pdf_path: Path,
    *,
    timeout: float,
    pdfimages_executable: str = "pdfimages",
) -> tuple[int, ...]:
    if shutil.which(pdfimages_executable) is None:
        return ()
    completed = subprocess.run(
        [pdfimages_executable, "-list", str(pdf_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        return ()
    return _parse_pdfimages_pages(completed.stdout + "\n" + completed.stderr)


def _native_pdf_pages(
    pdf_path: Path,
    *,
    timeout: float,
    pdftotext_executable: str = "pdftotext",
    pdfinfo_executable: str = "pdfinfo",
) -> tuple[str, ...]:
    """Extract text per page so one hidden scan cannot hide inside a good PDF."""

    if shutil.which(pdftotext_executable) is None or shutil.which(pdfinfo_executable) is None:
        return ()
    info = subprocess.run(
        [pdfinfo_executable, str(pdf_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    match = PAGES_PATTERN.search(info.stdout)
    if info.returncode != 0 or match is None:
        return ()
    page_count = int(match.group(1))
    extracted = subprocess.run(
        [pdftotext_executable, "-layout", "-enc", "UTF-8", str(pdf_path), "-"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if extracted.returncode != 0:
        return ()
    pages = extracted.stdout.split("\f")
    if len(pages) > page_count:
        pages = pages[:page_count]
    if len(pages) < page_count:
        pages.extend("" for _ in range(page_count - len(pages)))
    return tuple(pages)


def _rasterize_pages(
    pdf_path: Path,
    output_root: Path,
    page_numbers: tuple[int, ...],
    *,
    timeout: float,
    pdftoppm_executable: str = "pdftoppm",
) -> tuple[Path, ...]:
    if not page_numbers or shutil.which(pdftoppm_executable) is None:
        return ()
    scan_dir = output_root / f"scan-{pdf_path.stem}"
    scan_dir.mkdir(parents=True, exist_ok=True)
    images = []
    for page_number in page_numbers:
        prefix = scan_dir / f"page-{page_number:04d}"
        completed = subprocess.run(
            [
                pdftoppm_executable,
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-singlefile",
                "-r",
                "200",
                "-png",
                str(pdf_path),
                str(prefix),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        image_path = prefix.with_suffix(".png")
        if completed.returncode != 0 or not image_path.is_file():
            message = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(message or f"pdftoppm failed for page {page_number}")
        images.append(image_path)
    return tuple(images)


def extract_documents(
    layout: DatasetLayout,
    output_dir: Path,
    extractor: CascadeExtractor,
    *,
    limit: int | None,
    timeout: float,
    rasterize_low_text_pages: bool = True,
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
            low_text_pages: tuple[int, ...] = ()
            embedded_image_pages: tuple[int, ...] = ()
            scan_images: tuple[Path, ...] = ()
            scan_detection_error = None
            if rasterize_low_text_pages:
                try:
                    native_pages = _native_pdf_pages(pdf_path, timeout=timeout)
                    low_text_pages = _low_text_page_numbers(native_pages)
                    embedded_image_pages = _embedded_image_page_numbers(
                        pdf_path, timeout=timeout
                    )
                    routed_pages = tuple(
                        sorted(set(low_text_pages) | set(embedded_image_pages))
                    )
                    scan_images = _rasterize_pages(
                        pdf_path,
                        output_dir.parent,
                        routed_pages,
                        timeout=timeout,
                    )
                except Exception as exc:
                    scan_detection_error = str(exc)[:1000]
            record = {
                "index": index,
                "source": str(pdf_path),
                "output": str(output_path),
                "status": "success" if result.quality.passed else "low_quality",
                "selected_backend": result.selected_backend,
                "quality": result.quality.to_dict(),
                "account_ids": sorted(set(ACCOUNT_PATTERN.findall(result.markdown))),
                "attempts": [attempt.to_dict() for attempt in result.attempts],
                "low_text_pages": list(low_text_pages),
                "embedded_image_pages": list(embedded_image_pages),
                "scan_images": [str(path) for path in scan_images],
            }
            if scan_detection_error is not None:
                record["scan_detection_error"] = scan_detection_error
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
        "scan_document_count": sum(bool(row.get("scan_images")) for row in records),
        "scan_page_count": sum(len(row.get("scan_images", [])) for row in records),
        "documents": records,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
