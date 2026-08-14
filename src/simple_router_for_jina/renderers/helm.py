"""Render a self-contained Helm chart bundle."""

from __future__ import annotations

from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any

import yaml

from simple_router_for_jina.compiler import DeploymentIR
from simple_router_for_jina.config.schema import ExposureMode


def _copy_tree(node: Traversable, prefix: str = "") -> dict[str, str]:
    output: dict[str, str] = {}
    for child in sorted(node.iterdir(), key=lambda item: item.name):
        relative = f"{prefix}/{child.name}" if prefix else child.name
        if child.is_dir():
            output.update(_copy_tree(child, relative))
        else:
            output[relative] = child.read_text(encoding="utf-8")
    return output


def _values(ir: DeploymentIR) -> dict[str, Any]:
    gateway_enabled = ir.exposure_mode is ExposureMode.GATEWAY
    services = []
    for service in ir.services:
        services.append(
            {
                "role": service.role,
                "model": service.model,
                "image": service.image,
                "imagePullPolicy": "IfNotPresent",
                "replicas": service.replicas,
                "containerPort": service.container_port,
                "servicePort": service.container_port if gateway_enabled else ir.exposure_port,
                "env": dict(service.env),
                "readOnlyRootFilesystem": ir.production.read_only_root_filesystem,
                "resources": {
                    "cpu": service.resources.cpu,
                    "memory": service.resources.memory,
                    "gpu": service.resources.gpu,
                },
            }
        )
    return {
        "nameOverride": ir.name,
        "commonLabels": dict(ir.labels),
        "services": services,
        "serviceAccount": {"create": True, "name": ""},
        "gateway": {
            "enabled": gateway_enabled,
            "image": ir.gateway_image,
            "replicas": 2,
            "port": ir.exposure_port,
        },
        "networkPolicy": {"enabled": ir.production.network_policy},
        "ingress": {
            "enabled": False,
            "className": "",
            "annotations": {},
            "host": "",
            "tlsSecretName": "",
        },
    }


def render_helm(ir: DeploymentIR) -> dict[str, str]:
    """Render the packaged chart plus normalized generated values."""

    chart = files("simple_router_for_jina.resources").joinpath("charts", "jina-serving")
    output = _copy_tree(chart)
    output["values.generated.yaml"] = yaml.safe_dump(_values(ir), sort_keys=False, width=100)
    return output
