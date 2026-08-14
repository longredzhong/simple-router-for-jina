"""Offline model catalog loading."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Literal

from simple_router_for_jina.config.schema import Runtime

ModelRole = Literal["embedding", "reranker"]


@dataclass(frozen=True, slots=True)
class CatalogSource:
    """Provenance for the vendored catalog snapshot."""

    url: str
    revision: str
    synced_at: str


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """Deployment capabilities for one model image."""

    id: str
    role: ModelRole
    repository: str
    runtimes: tuple[Runtime, ...]
    default_cpu: str
    default_memory: str


@dataclass(frozen=True, slots=True)
class Catalog:
    """Immutable catalog snapshot."""

    source: CatalogSource
    entries: tuple[CatalogEntry, ...]

    def get(self, model_id: str) -> CatalogEntry | None:
        return next((entry for entry in self.entries if entry.id == model_id), None)


def load_catalog() -> Catalog:
    """Load the packaged catalog without network access."""

    resource = files("simple_router_for_jina.resources").joinpath("catalog.json")
    raw: dict[str, Any] = json.loads(resource.read_text(encoding="utf-8"))
    source = raw["source"]
    entries = tuple(
        CatalogEntry(
            id=item["id"],
            role=item["role"],
            repository=item["repository"],
            runtimes=tuple(Runtime(value) for value in item["runtimes"]),
            default_cpu=item["defaultCpu"],
            default_memory=item["defaultMemory"],
        )
        for item in raw["models"]
    )
    return Catalog(
        source=CatalogSource(
            url=source["url"],
            revision=source["revision"],
            synced_at=source["syncedAt"],
        ),
        entries=entries,
    )
