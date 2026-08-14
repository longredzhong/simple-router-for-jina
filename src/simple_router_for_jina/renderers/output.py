"""Safe writing of deterministic renderer outputs."""

from __future__ import annotations

from pathlib import Path, PurePosixPath


class OutputError(ValueError):
    """Raised when renderer output would overwrite unmanaged files."""


def write_outputs(output_dir: Path, files: dict[str, str], *, force: bool = False) -> None:
    """Write renderer-owned files below an output directory."""

    paths: list[tuple[Path, str]] = []
    for relative, content in sorted(files.items()):
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise OutputError(f"unsafe renderer path: {relative}")
        destination = output_dir.joinpath(*pure.parts)
        if destination.exists() and not force:
            raise OutputError(f"{destination} already exists; use --force to replace it")
        paths.append((destination, content))

    for destination, content in paths:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
