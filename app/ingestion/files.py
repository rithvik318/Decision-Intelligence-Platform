from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.domain import SourceDocument

TEXT_SUFFIXES = {".md": "markdown", ".markdown": "markdown", ".txt": "text"}


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - installation guard
        raise RuntimeError("PDF ingestion requires `pypdf`.") from exc
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages).strip()


def load_file(path: Path) -> SourceDocument:
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"{path} is not a file")
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        content = path.read_text(encoding="utf-8", errors="replace").strip()
        document_type = TEXT_SUFFIXES[suffix]
    elif suffix == ".pdf":
        content = _read_pdf(path)
        document_type = "pdf"
    else:
        raise ValueError(f"Unsupported file type: {suffix or path.name}")
    if not content:
        raise ValueError(f"No extractable text in {path.name} (scanned PDFs need OCR)")
    timestamp = datetime.fromtimestamp(
        path.stat().st_mtime, tz=UTC
    ).isoformat()
    return SourceDocument(
        content=content,
        file_name=path.name,
        document_type=document_type,
        source="file",
        location=str(path.resolve()),
        timestamp=timestamp,
    )


def load_directory(directory: Path) -> list[SourceDocument]:
    supported = set(TEXT_SUFFIXES) | {".pdf"}
    files = sorted(
        p for p in Path(directory).rglob("*") if p.suffix.lower() in supported
    )
    return [load_file(p) for p in files]
