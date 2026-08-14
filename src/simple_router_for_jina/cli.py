"""Command-line interface for the deployment compiler."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click
import yaml
from pydantic import ValidationError

from simple_router_for_jina import __version__
from simple_router_for_jina.catalog import load_catalog
from simple_router_for_jina.compiler import CompilationError, compile_config
from simple_router_for_jina.config.loader import ConfigLoadError, load_config
from simple_router_for_jina.config.schema import API_VERSION, KIND, JinaServing, ServingMode
from simple_router_for_jina.renderers.compose import render_compose
from simple_router_for_jina.renderers.helm import render_helm
from simple_router_for_jina.renderers.kustomize import render_kustomize
from simple_router_for_jina.renderers.output import OutputError, write_outputs


def _abort_config(exc: Exception) -> None:
    if isinstance(exc, ValidationError):
        details = json.loads(exc.json(include_url=False))
        messages = []
        for error in details:
            location = ".".join(str(part) for part in error["loc"])
            messages.append(f"{location}: {error['msg']}")
        raise click.ClickException("configuration validation failed:\n- " + "\n- ".join(messages))
    raise click.ClickException(str(exc))


def _load_and_compile(path: Path) -> None:
    try:
        compile_config(load_config(path))
    except (CompilationError, ConfigLoadError, ValidationError) as exc:
        _abort_config(exc)


def _model_block(model: str, runtime: str = "cpu") -> dict[str, Any]:
    return {
        "model": model,
        "runtime": runtime,
        "replicas": 1,
        "resources": {"cpu": "4", "memory": "6Gi", "gpu": 0 if runtime == "cpu" else 1},
    }


def _starter(mode: ServingMode, name: str) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "mode": mode.value,
        "exposure": {"mode": "gateway", "port": 8080},
        "production": {
            "requireImageDigest": False,
            "networkPolicy": True,
            "readOnlyRootFilesystem": True,
        },
    }
    if mode in {ServingMode.EMBEDDING, ServingMode.COMBINED}:
        spec["embedding"] = _model_block("jina-embeddings-v5-text-small")
    if mode in {ServingMode.RERANKER, ServingMode.COMBINED}:
        spec["reranker"] = _model_block("jina-reranker-v3")
    return {
        "apiVersion": API_VERSION,
        "kind": KIND,
        "metadata": {"name": name, "namespace": "default"},
        "spec": spec,
    }


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__)
def cli() -> None:
    """Validate Jina services and render deployment artifacts."""


@cli.command("init")
@click.option("--mode", type=click.Choice([mode.value for mode in ServingMode]), required=True)
@click.option("--name", default="jina-serving", show_default=True)
@click.option(
    "--output", "output_path", type=click.Path(path_type=Path), default=Path("serving.yaml")
)
def init_config(mode: str, name: str, output_path: Path) -> None:
    """Create a starter serving definition."""

    if output_path.exists():
        raise click.ClickException(f"{output_path} already exists")
    content = yaml.safe_dump(_starter(ServingMode(mode), name), sort_keys=False)
    output_path.write_text(content, encoding="utf-8")
    click.echo(f"wrote {output_path}")


@cli.command("validate")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
def validate_config(config_path: Path) -> None:
    """Validate syntax, topology, catalog capability and production rules."""

    _load_and_compile(config_path)
    click.echo(f"valid: {config_path}")


@cli.command("schema")
@click.option("--output", "output_path", type=click.Path(dir_okay=False, path_type=Path))
def export_schema(output_path: Path | None) -> None:
    """Export the JSON Schema for the current configuration API."""

    content = (
        json.dumps(JinaServing.model_json_schema(by_alias=True), indent=2, sort_keys=True) + "\n"
    )
    if output_path is None:
        click.echo(content, nl=False)
        return
    output_path.write_text(content, encoding="utf-8")
    click.echo(f"wrote {output_path}")


@cli.group("catalog")
def catalog_group() -> None:
    """Inspect the vendored offline model catalog."""


@catalog_group.command("list")
@click.option("--role", type=click.Choice(["embedding", "reranker"]))
def list_catalog(role: str | None) -> None:
    """List supported models and runtimes."""

    catalog = load_catalog()
    click.echo("MODEL\tROLE\tRUNTIMES")
    for entry in catalog.entries:
        if role is None or entry.role == role:
            runtimes = ",".join(runtime.value for runtime in entry.runtimes)
            click.echo(f"{entry.id}\t{entry.role}\t{runtimes}")


@catalog_group.command("show")
@click.argument("model_id")
def show_catalog(model_id: str) -> None:
    """Show one model and the catalog provenance."""

    catalog = load_catalog()
    entry = catalog.get(model_id)
    if entry is None:
        raise click.ClickException(f"unknown model: {model_id}")
    result = {
        "id": entry.id,
        "role": entry.role,
        "repository": entry.repository,
        "runtimes": [runtime.value for runtime in entry.runtimes],
        "defaults": {"cpu": entry.default_cpu, "memory": entry.default_memory},
        "source": {
            "url": catalog.source.url,
            "revision": catalog.source.revision,
            "syncedAt": catalog.source.synced_at,
        },
    }
    click.echo(yaml.safe_dump(result, sort_keys=False), nl=False)


@cli.group("render")
def render_group() -> None:
    """Render target-specific deployment files."""


@render_group.command("compose")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option(
    "--output",
    "output_dir",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
)
@click.option("--force", is_flag=True, help="Replace renderer-owned files that already exist.")
def render_compose_command(config_path: Path, output_dir: Path, force: bool) -> None:
    """Render a Docker Compose deployment bundle."""

    try:
        deployment = compile_config(load_config(config_path))
        write_outputs(output_dir, render_compose(deployment), force=force)
    except (CompilationError, ConfigLoadError, OutputError, ValidationError) as exc:
        _abort_config(exc)
    click.echo(f"rendered compose bundle: {output_dir}")


@render_group.command("helm")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option(
    "--output",
    "output_dir",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
)
@click.option("--force", is_flag=True, help="Replace renderer-owned files that already exist.")
def render_helm_command(config_path: Path, output_dir: Path, force: bool) -> None:
    """Render a self-contained Helm chart bundle."""

    try:
        deployment = compile_config(load_config(config_path))
        write_outputs(output_dir, render_helm(deployment), force=force)
    except (CompilationError, ConfigLoadError, OutputError, ValidationError) as exc:
        _abort_config(exc)
    click.echo(f"rendered Helm bundle: {output_dir}")


@render_group.command("kustomize")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option(
    "--output",
    "output_dir",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
)
@click.option("--force", is_flag=True, help="Replace renderer-owned files that already exist.")
def render_kustomize_command(config_path: Path, output_dir: Path, force: bool) -> None:
    """Render a Kustomize base with dev and prod overlays."""

    try:
        deployment = compile_config(load_config(config_path))
        write_outputs(output_dir, render_kustomize(deployment), force=force)
    except (CompilationError, ConfigLoadError, OutputError, ValidationError) as exc:
        _abort_config(exc)
    click.echo(f"rendered Kustomize bundle: {output_dir}")
