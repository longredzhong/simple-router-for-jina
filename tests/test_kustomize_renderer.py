from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from simple_router_for_jina.cli import cli
from simple_router_for_jina.compiler import compile_config
from simple_router_for_jina.config.loader import load_config
from simple_router_for_jina.renderers.kustomize import render_kustomize

EXAMPLES = Path(__file__).parents[1] / "examples"


def _render(filename: str) -> dict[str, str]:
    return render_kustomize(compile_config(load_config(EXAMPLES / filename)))


def test_bundle_reuses_canonical_helm_chart() -> None:
    files = _render("combined.yaml")

    assert "base/charts/jina-serving/Chart.yaml" in files
    assert "base/charts/jina-serving/templates/model-deployments.yaml" in files
    assert "base/values.generated.yaml" in files


def test_base_uses_only_local_helm_inputs() -> None:
    files = _render("combined.yaml")
    kustomization = yaml.safe_load(files["base/kustomization.yaml"])
    chart = kustomization["helmCharts"][0]

    assert kustomization["namespace"] == "ai-serving"
    assert kustomization["helmGlobals"] == {"chartHome": "charts"}
    assert chart["name"] == "jina-serving"
    assert chart["releaseName"] == "search-models"
    assert chart["valuesFile"] == "values.generated.yaml"
    assert "repo" not in chart


def test_overlays_are_explicit_and_non_destructive() -> None:
    files = _render("embedding.yaml")
    dev = yaml.safe_load(files["overlays/dev/kustomization.yaml"])
    prod = yaml.safe_load(files["overlays/prod/kustomization.yaml"])

    assert dev["resources"] == ["../../base"]
    assert prod["resources"] == ["../../base"]
    assert "/spec/replicas" in files["overlays/dev/replicas.yaml"]
    assert "topologySpreadConstraints" in files["overlays/prod/topology-spread.yaml"]


def test_cli_renders_kustomize_bundle(tmp_path: Path) -> None:
    output = tmp_path / "kustomize"

    result = CliRunner().invoke(
        cli,
        [
            "render",
            "kustomize",
            "--config",
            str(EXAMPLES / "combined.yaml"),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (output / "base" / "kustomization.yaml").is_file()
    assert (output / "overlays" / "dev" / "kustomization.yaml").is_file()
    assert (output / "overlays" / "prod" / "kustomization.yaml").is_file()
