from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from simple_router_for_jina.cli import cli
from simple_router_for_jina.compiler import compile_config
from simple_router_for_jina.config.loader import load_config
from simple_router_for_jina.renderers.helm import render_helm

EXAMPLES = Path(__file__).parents[1] / "examples"


def _render(filename: str) -> tuple[dict, dict[str, str]]:
    files = render_helm(compile_config(load_config(EXAMPLES / filename)))
    return yaml.safe_load(files["values.generated.yaml"]), files


def test_helm_bundle_contains_chart_and_generated_values() -> None:
    values, files = _render("combined.yaml")

    assert "Chart.yaml" in files
    assert "values.yaml" in files
    assert "templates/model-deployments.yaml" in files
    assert "templates/networkpolicy.yaml" in files
    assert values["nameOverride"] == "search-models"


def test_combined_values_keep_workloads_independent() -> None:
    values, _ = _render("combined.yaml")

    assert values["gateway"]["enabled"] is True
    assert values["gateway"]["port"] == 8080
    assert [service["role"] for service in values["services"]] == ["embedding", "reranker"]
    embedding, reranker = values["services"]
    assert embedding["replicas"] == 2
    assert embedding["resources"]["gpu"] == 1
    assert embedding["servicePort"] == 8080
    assert reranker["replicas"] == 1


def test_direct_values_map_public_service_port() -> None:
    values, _ = _render("embedding.yaml")

    assert values["gateway"]["enabled"] is False
    assert values["services"][0]["containerPort"] == 8080
    assert values["services"][0]["servicePort"] == 8080


def test_chart_contains_required_security_controls() -> None:
    _, files = _render("embedding.yaml")
    deployment = files["templates/model-deployments.yaml"]

    assert "runAsNonRoot: true" in deployment
    assert "readOnlyRootFilesystem:" in deployment
    assert 'drop: ["ALL"]' in deployment
    assert "startupProbe:" in deployment
    assert "readinessProbe:" in deployment
    assert "livenessProbe:" in deployment
    assert "nvidia.com/gpu:" in deployment


def test_cli_renders_self_contained_helm_bundle(tmp_path: Path) -> None:
    output = tmp_path / "chart"

    result = CliRunner().invoke(
        cli,
        [
            "render",
            "helm",
            "--config",
            str(EXAMPLES / "combined.yaml"),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (output / "Chart.yaml").is_file()
    assert (output / "values.generated.yaml").is_file()
    assert (output / "templates" / "gateway-deployment.yaml").is_file()
