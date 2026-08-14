"""Configuration loading and schema definitions."""

from simple_router_for_jina.config.loader import load_config
from simple_router_for_jina.config.schema import JinaServing

__all__ = ["JinaServing", "load_config"]
