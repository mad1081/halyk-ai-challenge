from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from halyk_agent.dataset import DatasetLayout
from halyk_agent.extraction.backends import CascadeExtractor


ACCOUNT_PATTERN = re.compile(r"\b(?:ACC|TELE)-\d+(?:-\d+)?\b", re.IGNORECASE)
PAGES_PATTERN = re.compile(r"^Pages:\s+(\d+)\s*$", re.IGNORECASE | re.MULTILINE)
SINGLE_IMAGE_COVERAGE_THRESHOLD = 0.02
UNION_IMAGE_COVERAGE_THRESHOLD = 0.03
PAGE_REPLACEMENT_RATIO_THRESHOLD = 0.005


def _low_text_page_numbers(page_texts: tuple[str, ...]) -> tuple[int, ...]:
    """Return 1-based pages whose native text layer is absent or corrupted.

    Digits are not evidence that prose survived PDF font decoding: a broken
    ToUnicode map can silently drop every letter while leaving amounts, dates,
    percentages, and IDs intact. Replacement characters are checked per page
    so a damaged covenant page cannot hide inside an otherwise clean document.
    """

    low_text = []
    for page_number, text in enumerate(page_texts, start=1):
        stripped = text.strip()
        character_count = len(stripped)
        alphabetic = sum(character.isalpha() for character in stripped)
        replacement_ratio = (
            stripped.count("\ufffd") / character_count if character_count else 1.0
        )
        if (
            character_count < 80
            or alphabetic < 40
            or replacement_ratio > PAGE_REPLACEMENT_RATIO_THRESHOLD
        ):
            low_text.append(page_number)
    return tuple(low_text)


def _parse_pdfimages_pages(output: str) -> tuple[int, ...]:
    """Fallback detector based on intrinsic image dimensions.

    Displayed page geometry is preferable because a low-resolution image can be
    stretched over most of a page and a high-resolution logo can be displayed
    very small. This parser remains useful when ``pdftohtml`` is unavailable.
    """

    pages = set()
    for line in output.splitlines():
        fields = line.split()
        if (
            len(fields) < 6
            or not fields[0].isdigit()
            or fields[2] not in {"image", "mask"}
        ):
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


def _rectangle_union_area(
    rectangles: tuple[tuple[float, float, float, float], ...],
) -> float:
    """Return the exact union area of a small set of axis-aligned rectangles."""

    if not rectangles:
        return 0.0
    x_coordinates = sorted({value for rect in rectangles for value in (rect[0], rect[2])})
    area = 0.0
    for left, right in zip(x_coordinates, x_coordinates[1:]):
        if right <= left:
            continue
        intervals = sorted(
            (top, bottom)
            for x0, top, x1, bottom in rectangles
            if x0 < right and x1 > left and bottom > top
        )
        if not intervals:
            continue
        covered_height = 0.0
        current_top, current_bottom = intervals[0]
        for top, bottom in intervals[1:]:
            if top <= current_bottom:
                current_bottom = max(current_bottom, bottom)
            else:
                covered_height += current_bottom - current_top
                current_top, current_bottom = top, bottom
        covered_height += current_bottom - current_top
        area += (right - left) * covered_height
    return area


def _parse_pdftohtml_image_analysis(
    output: str,
    *,
    single_image_threshold: float = SINGLE_IMAGE_COVERAGE_THRESHOLD,
    union_image_threshold: float = UNION_IMAGE_COVERAGE_THRESHOLD,
) -> tuple[dict, ...]:
    """Analyze the *displayed* image area reported by ``pdftohtml -xml``.

    Each result is retained for provenance, including pages below the routing
    threshold. Union coverage catches tiled scans whose individual raster tiles
    all look like small images. Coordinates are clipped to the visible page so
    malformed or deliberately oversized boxes cannot inflate the score.
    """

    root = ET.fromstring(output)
    analysis: list[dict] = []
    for page in root.iter("page"):
        try:
            page_number = int(page.attrib["number"])
            page_width = float(page.attrib["width"])
            page_height = float(page.attrib["height"])
        except (KeyError, TypeError, ValueError):
            continue
        page_area = page_width * page_height
        if page_area <= 0:
            continue
        rectangles: list[tuple[float, float, float, float]] = []
        for image in page.iter("image"):
            try:
                left = float(image.attrib["left"])
                top = float(image.attrib["top"])
                width = float(image.attrib["width"])
                height = float(image.attrib["height"])
            except (KeyError, TypeError, ValueError):
                continue
            right = min(page_width, max(0.0, left + width))
            bottom = min(page_height, max(0.0, top + height))
            left = min(page_width, max(0.0, left))
            top = min(page_height, max(0.0, top))
            if right > left and bottom > top:
                rectangles.append((left, top, right, bottom))
        if not rectangles:
            continue
        individual_coverages = [
            ((right - left) * (bottom - top)) / page_area
            for left, top, right, bottom in rectangles
        ]
        maximum_coverage = max(individual_coverages)
        union_coverage = _rectangle_union_area(tuple(rectangles)) / page_area
        reasons = []
        if maximum_coverage >= single_image_threshold:
            reasons.append("displayed_image_coverage")
        if union_coverage >= union_image_threshold:
            reasons.append("displayed_image_union_coverage")
        analysis.append(
            {
                "page": page_number,
                "detector": "pdftohtml_display_geometry",
                "image_count": len(rectangles),
                "max_image_coverage": round(maximum_coverage, 6),
                "union_image_coverage": round(union_coverage, 6),
                "routed": bool(reasons),
                "reasons": reasons or ["below_displayed_image_threshold"],
            }
        )
    return tuple(analysis)


def _embedded_image_page_analysis(
    pdf_path: Path,
    *,
    timeout: float,
    pdftohtml_executable: str = "pdftohtml",
    pdfimages_executable: str = "pdfimages",
) -> tuple[dict, ...]:
    """Inspect visible image geometry, with the old pixel heuristic as fallback."""

    if shutil.which(pdftohtml_executable) is not None:
        # Even with ``-stdout``, pdftohtml materializes referenced image files.
        # Isolate them so extraction never pollutes the dataset or current dir.
        with tempfile.TemporaryDirectory(prefix="halyk-pdftohtml-") as temporary:
            completed = subprocess.run(
                [
                    pdftohtml_executable,
                    "-xml",
                    "-stdout",
                    "-hidden",
                    str(pdf_path.resolve()),
                    "-",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                cwd=temporary,
            )
        if completed.returncode == 0:
            try:
                return _parse_pdftohtml_image_analysis(completed.stdout)
            except ET.ParseError:
                pass

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
    pages = _parse_pdfimages_pages(completed.stdout + "\n" + completed.stderr)
    return tuple(
        {
            "page": page,
            "detector": "pdfimages_intrinsic_fallback",
            "routed": True,
            "reasons": ["substantial_intrinsic_raster"],
        }
        for page in pages
    )


def _embedded_image_page_numbers(
    pdf_path: Path,
    *,
    timeout: float,
    pdftohtml_executable: str = "pdftohtml",
    pdfimages_executable: str = "pdfimages",
) -> tuple[int, ...]:
    analysis = _embedded_image_page_analysis(
        pdf_path,
        timeout=timeout,
        pdftohtml_executable=pdftohtml_executable,
        pdfimages_executable=pdfimages_executable,
    )
    return tuple(row["page"] for row in analysis if row["routed"])


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
            visual_page_analysis: tuple[dict, ...] = ()
            routed_pages: tuple[int, ...] = ()
            scan_images: tuple[Path, ...] = ()
            scan_detection_error = None
            if rasterize_low_text_pages:
                try:
                    native_pages = _native_pdf_pages(pdf_path, timeout=timeout)
                    low_text_pages = _low_text_page_numbers(native_pages)
                    visual_page_analysis = _embedded_image_page_analysis(
                        pdf_path, timeout=timeout
                    )
                    embedded_image_pages = tuple(
                        row["page"] for row in visual_page_analysis if row["routed"]
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
                "visual_page_analysis": list(visual_page_analysis),
                "routed_pages": list(routed_pages),
                "scan_page_provenance": [
                    {
                        "page": page,
                        "reasons": (
                            (["low_native_text"] if page in low_text_pages else [])
                            + next(
                                (
                                    row["reasons"]
                                    for row in visual_page_analysis
                                    if row["page"] == page and row["routed"]
                                ),
                                [],
                            )
                        ),
                        "image": next(
                            (str(path) for path in scan_images if path.stem == f"page-{page:04d}"),
                            None,
                        ),
                    }
                    for page in routed_pages
                ],
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
