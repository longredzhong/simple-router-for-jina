from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from simple_router_for_jina.cli import cli
from simple_router_for_jina.compiler import compile_config
from simple_router_for_jina.config.loader import load_config
from simple_router_for_jina.config.schema import JinaServing
from simple_router_for_jina.renderers.compose import render_compose
from simple_router_for_jina.renderers.output import OutputError, write_outputs

EXAMPLES = Path(__file__).parents[1] / "examples"


def _render(filename: str) -> tuple[dict, dict[str, str]]:
    files = render_compose(compile_config(load_config(EXAMPLES / filename)))
    return yaml.safe_load(files["compose.yaml"]), files


def test_direct_embedding_publishes_only_model_port() -> None:
    compose, files = _render("embedding.yaml")

    assert set(compose["services"]) == {"embedding"}
    assert compose["services"]["embedding"]["ports"] == ["8080:8080"]
    assert "gateway/nginx.conf" not in files


def test_combined_uses_gateway_and_private_model_ports() -> None:
    compose, files = _render("combined.yaml")

    assert set(compose["services"]) == {"embedding", "reranker", "gateway"}
    assert "ports" not in compose["services"]["embedding"]
    assert "ports" not in compose["services"]["reranker"]
    assert compose["services"]["gateway"]["ports"] == ["8080:8080"]
    assert compose["services"]["gateway"]["image"].startswith(
        "docker.io/nginxinc/nginx-unprivileged:"
    )
    assert compose["services"]["gateway"]["depends_on"] == {
        "embedding": {"condition": "service_healthy"},
        "reranker": {"condition": "service_healthy"},
    }
    assert "location = /v1/rerank" in files["gateway/nginx.conf"]
    assert "location = /v1/embeddings" in files["gateway/nginx.conf"]


def test_model_services_have_security_and_gpu_reservation() -> None:
    compose, _ = _render("reranker.yaml")
    service = compose["services"]["reranker"]

    assert service["user"] == "65534:65534"
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["deploy"]["resources"]["limits"]["memory"] == "6g"
    assert service["healthcheck"]["test"][-1] == "http://localhost:8080/health"
    device = service["deploy"]["resources"]["reservations"]["devices"][0]
    assert device == {"driver": "nvidia", "count": 1, "capabilities": ["gpu"]}


def test_rendered_bundle_has_only_relative_mounts() -> None:
    compose, _ = _render("combined.yaml")

    assert compose["services"]["gateway"]["volumes"] == [
        "./gateway/nginx.conf:/etc/nginx/conf.d/default.conf:ro"
    ]


def test_output_writer_refuses_existing_file_without_force(tmp_path: Path) -> None:
    files = {"compose.yaml": "name: first\n"}
    write_outputs(tmp_path, files)

    with pytest.raises(OutputError, match="already exists"):
        write_outputs(tmp_path, files)

    write_outputs(tmp_path, {"compose.yaml": "name: second\n"}, force=True)
    assert (tmp_path / "compose.yaml").read_text() == "name: second\n"


def test_cli_renders_compose_bundle(tmp_path: Path) -> None:
    output = tmp_path / "bundle"

    result = CliRunner().invoke(
        cli,
        [
            "render",
            "compose",
            "--config",
            str(EXAMPLES / "combined.yaml"),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (output / "compose.yaml").is_file()
    assert (output / "gateway" / "nginx.conf").is_file()


def test_compose_secret_uses_required_host_environment() -> None:
    raw = yaml.safe_load((EXAMPLES / "embedding.yaml").read_text())
    raw["spec"]["embedding"]["secretEnv"] = [
        {
            "name": "JINA_LICENSE_KEY",
            "composeEnvironment": "DEPLOYMENT_LICENSE",
            "kubernetesSecret": {"name": "jina-license", "key": "license-key"},
        }
    ]

    files = render_compose(compile_config(JinaServing.model_validate(raw)))
    compose = yaml.safe_load(files["compose.yaml"])

    assert compose["services"]["embedding"]["environment"]["JINA_LICENSE_KEY"] == (
        "${DEPLOYMENT_LICENSE:?set DEPLOYMENT_LICENSE}"
    )
