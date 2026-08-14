"""Load a YAML source file into the strict schema."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from simple_router_for_jina.config.schema import JinaServing


class ConfigLoadError(ValueError):
    """Raised when the source is not a valid YAML mapping."""


def load_config(path: Path) -> JinaServing:
    """Parse and validate a serving definition."""

    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigLoadError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigLoadError(f"invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigLoadError(f"{path} must contain a YAML mapping")
    return JinaServing.model_validate(raw)
