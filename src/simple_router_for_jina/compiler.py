"""Compile validated source configuration into a renderer-neutral IR."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from simple_router_for_jina.catalog import Catalog, CatalogEntry, load_catalog
from simple_router_for_jina.config.schema import (
    ExposureMode,
    JinaServing,
    ModelSpec,
    Runtime,
    ServingMode,
)

ModelRole = Literal["embedding", "reranker"]


class CompilationError(ValueError):
    """Raised when valid syntax violates catalog or deployment constraints."""


@dataclass(frozen=True, slots=True)
class ResourceIR:
    """Normalized portable resources."""

    cpu: str
    memory: str
    gpu: int


@dataclass(frozen=True, slots=True)
class ServiceIR:
    """A single model workload."""

    name: str
    role: ModelRole
    model: str
    runtime: Runtime
    image: str
    replicas: int
    resources: ResourceIR
    env: tuple[tuple[str, str], ...]
    container_port: int = 8080


@dataclass(frozen=True, slots=True)
class ProductionIR:
    """Renderer-independent hardening settings."""

    require_image_digest: bool
    network_policy: bool
    read_only_root_filesystem: bool


@dataclass(frozen=True, slots=True)
class DeploymentIR:
    """Complete normalized deployment."""

    name: str
    namespace: str
    labels: tuple[tuple[str, str], ...]
    mode: ServingMode
    services: tuple[ServiceIR, ...]
    exposure_mode: ExposureMode
    exposure_port: int
    production: ProductionIR


def _compile_service(
    *,
    deployment_name: str,
    role: ModelRole,
    spec: ModelSpec,
    catalog: Catalog,
    require_digest: bool,
) -> ServiceIR:
    entry: CatalogEntry | None = catalog.get(spec.model)
    if entry is None:
        raise CompilationError(f"model {spec.model!r} is not present in the vendored catalog")
    if entry.role != role:
        raise CompilationError(
            f"model {spec.model!r} has role {entry.role!r}, not requested role {role!r}"
        )
    if spec.runtime not in entry.runtimes:
        supported = ", ".join(runtime.value for runtime in entry.runtimes)
        raise CompilationError(
            f"model {spec.model!r} does not support runtime {spec.runtime.value!r}; "
            f"supported: {supported}"
        )
    if require_digest and spec.image.digest is None:
        raise CompilationError(f"model {spec.model!r} requires image.digest in production mode")

    default_gpu = 0 if spec.runtime is Runtime.CPU else 1
    gpu = spec.resources.gpu if spec.resources.gpu is not None else default_gpu
    if spec.runtime is Runtime.CPU and gpu != 0:
        raise CompilationError(f"CPU model {spec.model!r} cannot request a GPU")
    if spec.runtime is not Runtime.CPU and gpu < 1:
        raise CompilationError(f"GPU model {spec.model!r} must request at least one GPU")

    repository = spec.image.repository or entry.repository
    image = (
        f"{repository}@{spec.image.digest}"
        if spec.image.digest is not None
        else f"{repository}:{spec.runtime.value}"
    )
    return ServiceIR(
        name=f"{deployment_name}-{role}",
        role=role,
        model=spec.model,
        runtime=spec.runtime,
        image=image,
        replicas=spec.replicas,
        resources=ResourceIR(
            cpu=spec.resources.cpu or entry.default_cpu,
            memory=spec.resources.memory or entry.default_memory,
            gpu=gpu,
        ),
        env=tuple(sorted(spec.env.items())),
    )


def compile_config(config: JinaServing, catalog: Catalog | None = None) -> DeploymentIR:
    """Compile one validated configuration into immutable IR."""

    catalog = catalog or load_catalog()
    services: list[ServiceIR] = []
    require_digest = config.spec.production.require_image_digest
    if config.spec.embedding is not None:
        services.append(
            _compile_service(
                deployment_name=config.metadata.name,
                role="embedding",
                spec=config.spec.embedding,
                catalog=catalog,
                require_digest=require_digest,
            )
        )
    if config.spec.reranker is not None:
        services.append(
            _compile_service(
                deployment_name=config.metadata.name,
                role="reranker",
                spec=config.spec.reranker,
                catalog=catalog,
                require_digest=require_digest,
            )
        )

    return DeploymentIR(
        name=config.metadata.name,
        namespace=config.metadata.namespace,
        labels=tuple(sorted(config.metadata.labels.items())),
        mode=config.spec.mode,
        services=tuple(services),
        exposure_mode=config.spec.exposure.mode,
        exposure_port=config.spec.exposure.port,
        production=ProductionIR(
            require_image_digest=require_digest,
            network_policy=config.spec.production.network_policy,
            read_only_root_filesystem=config.spec.production.read_only_root_filesystem,
        ),
    )
