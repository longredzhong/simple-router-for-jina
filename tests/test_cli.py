from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from simple_router_for_jina.cli import cli

EXAMPLES = Path(__file__).parents[1] / "examples"


def test_validate_command_accepts_combined_example() -> None:
    result = CliRunner().invoke(cli, ["validate", "--config", str(EXAMPLES / "combined.yaml")])

    assert result.exit_code == 0, result.output
    assert "valid:" in result.output


def test_catalog_lists_role_capabilities() -> None:
    result = CliRunner().invoke(cli, ["catalog", "list", "--role", "reranker"])

    assert result.exit_code == 0, result.output
    assert "jina-reranker-v3\treranker\tcpu,gpu" in result.output
    assert "jina-embeddings-v3" not in result.output


def test_schema_uses_public_aliases() -> None:
    result = CliRunner().invoke(cli, ["schema"])

    assert result.exit_code == 0, result.output
    schema = json.loads(result.output)
    assert "apiVersion" in schema["properties"]
    production = schema["$defs"]["ProductionSpec"]["properties"]
    assert "requireImageDigest" in production


def test_init_creates_valid_configuration() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            ["init", "--mode", "combined", "--name", "demo", "--output", "serving.yaml"],
        )
        validate = runner.invoke(cli, ["validate", "--config", "serving.yaml"])

    assert result.exit_code == 0, result.output
    assert validate.exit_code == 0, validate.output


def test_validation_error_reports_field_location(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("apiVersion: wrong\nkind: JinaServing\nmetadata: {}\nspec: {}\n")

    result = CliRunner().invoke(cli, ["validate", "--config", str(invalid)])

    assert result.exit_code != 0
    assert "apiVersion" in result.output
