from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from simple_router_for_jina.compiler import CompilationError, compile_config
from simple_router_for_jina.config.loader import load_config
from simple_router_for_jina.config.schema import JinaServing, Runtime, ServingMode

EXAMPLES = Path(__file__).parents[1] / "examples"


@pytest.mark.parametrize(
    ("filename", "mode", "service_count"),
    [
        ("embedding.yaml", ServingMode.EMBEDDING, 1),
        ("reranker.yaml", ServingMode.RERANKER, 1),
        ("combined.yaml", ServingMode.COMBINED, 2),
    ],
)
def test_examples_compile(filename: str, mode: ServingMode, service_count: int) -> None:
    deployment = compile_config(load_config(EXAMPLES / filename))

    assert deployment.mode is mode
    assert len(deployment.services) == service_count


def test_compiler_sorts_environment_for_deterministic_ir() -> None:
    raw = yaml.safe_load((EXAMPLES / "embedding.yaml").read_text())
    raw["spec"]["embedding"]["env"] = {"Z_LAST": "2", "A_FIRST": "1"}

    deployment = compile_config(JinaServing.model_validate(raw))

    assert deployment.services[0].env == (("A_FIRST", "1"), ("Z_LAST", "2"))


def test_unknown_field_is_rejected() -> None:
    raw = yaml.safe_load((EXAMPLES / "embedding.yaml").read_text())
    raw["spec"]["embedding"]["replica"] = 2

    with pytest.raises(ValidationError, match="replica"):
        JinaServing.model_validate(raw)


def test_mode_requires_exact_service_shape() -> None:
    raw = yaml.safe_load((EXAMPLES / "embedding.yaml").read_text())
    raw["spec"]["mode"] = "combined"

    with pytest.raises(ValidationError, match="combined mode requires"):
        JinaServing.model_validate(raw)


def test_model_role_must_match_slot() -> None:
    raw = yaml.safe_load((EXAMPLES / "embedding.yaml").read_text())
    raw["spec"]["embedding"]["model"] = "jina-reranker-v3"

    with pytest.raises(CompilationError, match="not requested role"):
        compile_config(JinaServing.model_validate(raw))


def test_gpu_opt_is_rejected_for_reranker() -> None:
    raw = yaml.safe_load((EXAMPLES / "reranker.yaml").read_text())
    raw["spec"]["reranker"]["runtime"] = "gpu-opt"

    with pytest.raises(CompilationError, match="does not support runtime"):
        compile_config(JinaServing.model_validate(raw))


def test_production_mode_requires_digest() -> None:
    raw = yaml.safe_load((EXAMPLES / "embedding.yaml").read_text())
    raw["spec"]["production"]["requireImageDigest"] = True

    with pytest.raises(CompilationError, match="requires image.digest"):
        compile_config(JinaServing.model_validate(raw))


def test_digest_produces_immutable_image_reference() -> None:
    raw = yaml.safe_load((EXAMPLES / "embedding.yaml").read_text())
    digest = "sha256:" + "a" * 64
    raw["spec"]["production"]["requireImageDigest"] = True
    raw["spec"]["embedding"]["image"] = {"digest": digest}

    deployment = compile_config(JinaServing.model_validate(raw))

    assert deployment.services[0].runtime is Runtime.CPU
    assert deployment.services[0].image.endswith(f"@{digest}")


def test_production_gateway_requires_digest() -> None:
    raw = yaml.safe_load((EXAMPLES / "combined.yaml").read_text())
    digest = "sha256:" + "a" * 64
    raw["spec"]["production"]["requireImageDigest"] = True
    raw["spec"]["embedding"]["image"] = {"digest": digest}
    raw["spec"]["reranker"]["image"] = {"digest": digest}

    with pytest.raises(CompilationError, match="gateway requires"):
        compile_config(JinaServing.model_validate(raw))


def test_production_gateway_accepts_digest() -> None:
    raw = yaml.safe_load((EXAMPLES / "combined.yaml").read_text())
    digest = "sha256:" + "a" * 64
    raw["spec"]["production"]["requireImageDigest"] = True
    raw["spec"]["embedding"]["image"] = {"digest": digest}
    raw["spec"]["reranker"]["image"] = {"digest": digest}
    raw["spec"]["exposure"]["gatewayImage"] = f"example.invalid/gateway@{digest}"

    deployment = compile_config(JinaServing.model_validate(raw))

    assert deployment.gateway_image.endswith(f"@{digest}")
