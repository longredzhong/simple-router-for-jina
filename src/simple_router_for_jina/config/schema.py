"""Strict, versioned source configuration schema."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

API_VERSION = "serving.jina.ai/v1alpha1"
KIND = "JinaServing"
DNS_LABEL = re.compile(r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?$")
MEMORY_QUANTITY = re.compile(r"^[1-9][0-9]*(?:Mi|Gi|Ti)$")
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SECRET_ENV_NAME = re.compile(
    r"(?:^|_)(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|LICENSE_KEY|CREDENTIALS?)(?:$|_)"
)
SECRET_KEY = re.compile(r"^[A-Za-z0-9._-]+$")
DEFAULT_GATEWAY_IMAGE = "docker.io/nginxinc/nginx-unprivileged:1.29.1-alpine"


class StrictModel(BaseModel):
    """Base model that rejects unknown values."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ServingMode(StrEnum):
    EMBEDDING = "embedding"
    RERANKER = "reranker"
    COMBINED = "combined"


class Runtime(StrEnum):
    CPU = "cpu"
    GPU = "gpu"
    GPU_OPT = "gpu-opt"


class ExposureMode(StrEnum):
    DIRECT = "direct"
    GATEWAY = "gateway"


class Metadata(StrictModel):
    """Names used by all deployment targets."""

    name: str
    namespace: str = "default"
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("name", "namespace")
    @classmethod
    def validate_dns_label(cls, value: str) -> str:
        if not DNS_LABEL.fullmatch(value):
            raise ValueError("must be a lowercase DNS label with at most 63 characters")
        return value


class ImageSpec(StrictModel):
    """Optional overrides for a catalog image."""

    repository: str | None = None
    digest: str | None = None

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or "@" in value):
            raise ValueError("must be a non-empty repository without a digest")
        return value

    @field_validator("digest")
    @classmethod
    def validate_digest(cls, value: str | None) -> str | None:
        if value is not None and not IMAGE_DIGEST.fullmatch(value):
            raise ValueError("must be a sha256 OCI digest")
        return value


class ResourceSpec(StrictModel):
    """Portable resource settings normalized by the compiler."""

    cpu: str | None = None
    memory: str | None = None
    gpu: int | None = Field(default=None, ge=0, le=16)

    @field_validator("cpu")
    @classmethod
    def validate_cpu(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("must be a positive decimal string") from exc
        if parsed <= 0:
            raise ValueError("must be greater than zero")
        return value

    @field_validator("memory")
    @classmethod
    def validate_memory(cls, value: str | None) -> str | None:
        if value is not None and not MEMORY_QUANTITY.fullmatch(value):
            raise ValueError("must use a positive Mi, Gi, or Ti quantity")
        return value


class KubernetesSecretRef(StrictModel):
    """Reference to an existing Kubernetes Secret key."""

    name: str
    key: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not DNS_LABEL.fullmatch(value):
            raise ValueError("must be a lowercase Kubernetes Secret name")
        return value

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        if not SECRET_KEY.fullmatch(value):
            raise ValueError("must be a valid Kubernetes Secret data key")
        return value


class SecretEnvSpec(StrictModel):
    """Cross-target reference to a secret that already exists externally."""

    name: str
    compose_environment: str | None = Field(default=None, alias="composeEnvironment")
    kubernetes_secret: KubernetesSecretRef = Field(alias="kubernetesSecret")

    @field_validator("name", "compose_environment")
    @classmethod
    def validate_environment_name(cls, value: str | None) -> str | None:
        if value is not None and not ENV_NAME.fullmatch(value):
            raise ValueError("must be a valid environment variable name")
        return value


class ModelSpec(StrictModel):
    """A single model workload definition."""

    model: str = Field(min_length=1)
    runtime: Runtime = Runtime.CPU
    image: ImageSpec = Field(default_factory=ImageSpec)
    replicas: int = Field(default=1, ge=1, le=100)
    resources: ResourceSpec = Field(default_factory=ResourceSpec)
    env: dict[str, str] = Field(default_factory=dict)
    secret_env: list[SecretEnvSpec] = Field(default_factory=list, alias="secretEnv")

    @field_validator("env")
    @classmethod
    def validate_environment(cls, value: dict[str, str]) -> dict[str, str]:
        invalid = sorted(name for name in value if not ENV_NAME.fullmatch(name))
        if invalid:
            raise ValueError(f"invalid environment variable names: {', '.join(invalid)}")
        sensitive = sorted(name for name in value if SECRET_ENV_NAME.search(name))
        if sensitive:
            raise ValueError("secret-like variables must use secretEnv: " + ", ".join(sensitive))
        return value

    @model_validator(mode="after")
    def validate_secret_environment(self) -> ModelSpec:
        secret_names = [item.name for item in self.secret_env]
        duplicates = sorted(name for name in set(secret_names) if secret_names.count(name) > 1)
        overlap = sorted(set(self.env).intersection(secret_names))
        if duplicates:
            raise ValueError(f"duplicate secretEnv names: {', '.join(duplicates)}")
        if overlap:
            raise ValueError(f"variables cannot appear in env and secretEnv: {', '.join(overlap)}")
        return self


class ExposureSpec(StrictModel):
    """Public access shape shared across renderers."""

    mode: ExposureMode = ExposureMode.GATEWAY
    port: int = Field(default=8080, ge=1, le=65535)
    gateway_image: str = Field(default=DEFAULT_GATEWAY_IMAGE, alias="gatewayImage", min_length=1)


class ProductionSpec(StrictModel):
    """Deployment hardening switches."""

    require_image_digest: bool = Field(default=False, alias="requireImageDigest")
    network_policy: bool = Field(default=True, alias="networkPolicy")
    read_only_root_filesystem: bool = Field(default=True, alias="readOnlyRootFilesystem")


class ServingSpec(StrictModel):
    """Desired service topology."""

    mode: ServingMode
    embedding: ModelSpec | None = None
    reranker: ModelSpec | None = None
    exposure: ExposureSpec = Field(default_factory=ExposureSpec)
    production: ProductionSpec = Field(default_factory=ProductionSpec)

    @model_validator(mode="after")
    def validate_topology(self) -> ServingSpec:
        if self.mode is ServingMode.EMBEDDING:
            if self.embedding is None or self.reranker is not None:
                raise ValueError("embedding mode requires only spec.embedding")
        elif self.mode is ServingMode.RERANKER:
            if self.reranker is None or self.embedding is not None:
                raise ValueError("reranker mode requires only spec.reranker")
        elif self.embedding is None or self.reranker is None:
            raise ValueError("combined mode requires spec.embedding and spec.reranker")

        if self.mode is ServingMode.COMBINED and self.exposure.mode is not ExposureMode.GATEWAY:
            raise ValueError("combined mode requires exposure.mode=gateway")
        return self


class JinaServing(StrictModel):
    """Root deployment definition."""

    api_version: str = Field(alias="apiVersion")
    kind: str
    metadata: Metadata
    spec: ServingSpec

    @field_validator("api_version")
    @classmethod
    def validate_api_version(cls, value: str) -> str:
        if value != API_VERSION:
            raise ValueError(f"unsupported apiVersion; expected {API_VERSION}")
        return value

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        if value != KIND:
            raise ValueError(f"unsupported kind; expected {KIND}")
        return value
