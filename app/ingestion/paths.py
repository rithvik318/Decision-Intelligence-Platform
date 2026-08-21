"""Ingestion path safety.

`paths` on the ingest request names files the *server* reads, so an unchecked
value lets any caller pull arbitrary local files into a workspace and read them
back through chat. Every path is resolved and confined below a configured root.
"""

from __future__ import annotations

from pathlib import Path


class UnsafeIngestPath(ValueError):
    """The requested path resolves outside the permitted ingestion root."""


def resolve_within(candidate: Path | str, root: Path) -> Path:
    """Resolve `candidate` and confirm it sits inside `root`.

    Resolution happens first, so `..` segments and symlinks are normalised
    before the check rather than being pattern-matched away.
    """
    resolved = Path(candidate).expanduser().resolve()
    root = Path(root).expanduser().resolve()
    if resolved != root and root not in resolved.parents:
        raise UnsafeIngestPath(
            f"'{candidate}' is outside the permitted ingestion root. "
            "Set INGEST_ROOT to widen it, or upload the document inline."
        )
    return resolved
