from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import zipfile


class DatasetError(ValueError):
    """Raised when a challenge dataset is missing or malformed."""


@dataclass(frozen=True, slots=True)
class DatasetLayout:
    root: Path
    ledger_path: Path
    documents_dir: Path
    template_path: Path
    ground_truth_path: Path | None

    @classmethod
    def discover(cls, root: Path) -> "DatasetLayout":
        root = root.resolve()
        if not root.is_dir():
            raise DatasetError(f"Dataset directory does not exist: {root}")

        candidate = _find_dataset_root(root)
        ledger = candidate / "master_ledger_2025.csv"
        documents = candidate / "documents"
        template = candidate / "submission_template.json"
        missing = [str(path) for path in (ledger, documents, template) if not path.exists()]
        if missing:
            raise DatasetError("Missing required dataset paths: " + ", ".join(missing))
        if not documents.is_dir():
            raise DatasetError(f"Documents path is not a directory: {documents}")

        ground_truth = candidate / "ground_truth.json"
        return cls(
            root=candidate,
            ledger_path=ledger,
            documents_dir=documents,
            template_path=template,
            ground_truth_path=ground_truth if ground_truth.is_file() else None,
        )

    def load_template(self) -> dict:
        data = json.loads(self.template_path.read_text(encoding="utf-8-sig"))
        if not isinstance(data.get("answers"), dict) or not data["answers"]:
            raise DatasetError("submission_template.json has no non-empty 'answers' object")
        return data

    @property
    def pdf_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                (path for path in self.documents_dir.iterdir() if path.suffix.lower() == ".pdf"),
                key=lambda path: (path.name.casefold(), path.name),
            )
        )


def materialize_dataset(source: Path, work_dir: Path) -> DatasetLayout:
    source = source.resolve()
    if source.is_dir():
        return DatasetLayout.discover(source)
    if source.suffix.lower() != ".zip" or not source.is_file():
        raise DatasetError(f"Expected a dataset directory or ZIP archive: {source}")

    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    destination = work_dir.resolve() / "datasets" / digest
    marker = destination / ".extracted-ok"
    if not marker.exists():
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(source) as archive:
            for member in archive.infolist():
                _validate_zip_member(member.filename)
            archive.extractall(destination)
        marker.write_text(digest + "\n", encoding="utf-8")
    return DatasetLayout.discover(destination)


def dataset_fingerprint(layout: DatasetLayout) -> str:
    digest = hashlib.sha256()
    paths = [layout.ledger_path, layout.template_path, *layout.pdf_paths]
    for path in paths:
        digest.update(path.relative_to(layout.root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _find_dataset_root(root: Path) -> Path:
    if (root / "master_ledger_2025.csv").is_file():
        return root
    candidates = [
        child
        for child in root.iterdir()
        if child.is_dir() and (child / "master_ledger_2025.csv").is_file()
    ]
    if len(candidates) == 1:
        return candidates[0]
    return root


def _validate_zip_member(name: str) -> None:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise DatasetError(f"Unsafe ZIP member path: {name}")
    if path.parts and ":" in path.parts[0]:
        raise DatasetError(f"Unsafe ZIP member drive path: {name}")

