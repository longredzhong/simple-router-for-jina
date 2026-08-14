"""Kustomize renderer backed by the canonical packaged Helm chart."""

from __future__ import annotations

from typing import Any

import yaml

from simple_router_for_jina.compiler import DeploymentIR
from simple_router_for_jina.renderers.helm import render_helm


def _dump(value: dict[str, Any]) -> str:
    return yaml.safe_dump(value, sort_keys=False, width=100)


def render_kustomize(ir: DeploymentIR) -> dict[str, str]:
    """Render a local Helm-powered Kustomize base and environment overlays."""

    output: dict[str, str] = {}
    for relative, content in render_helm(ir).items():
        if relative == "values.generated.yaml":
            output["base/values.generated.yaml"] = content
        else:
            output[f"base/charts/jina-serving/{relative}"] = content

    output["base/kustomization.yaml"] = _dump(
        {
            "apiVersion": "kustomize.config.k8s.io/v1beta1",
            "kind": "Kustomization",
            "namespace": ir.namespace,
            "helmGlobals": {"chartHome": "charts"},
            "helmCharts": [
                {
                    "name": "jina-serving",
                    "releaseName": ir.name,
                    "namespace": ir.namespace,
                    "valuesFile": "values.generated.yaml",
                    "includeCRDs": False,
                }
            ],
        }
    )
    output["overlays/dev/kustomization.yaml"] = _dump(
        {
            "apiVersion": "kustomize.config.k8s.io/v1beta1",
            "kind": "Kustomization",
            "resources": ["../../base"],
            "patches": [{"path": "replicas.yaml", "target": {"kind": "Deployment"}}],
        }
    )
    output["overlays/dev/replicas.yaml"] = """\
- op: replace
  path: /spec/replicas
  value: 1
"""
    output["overlays/prod/kustomization.yaml"] = _dump(
        {
            "apiVersion": "kustomize.config.k8s.io/v1beta1",
            "kind": "Kustomization",
            "resources": ["../../base"],
            "patches": [{"path": "topology-spread.yaml", "target": {"kind": "Deployment"}}],
        }
    )
    output["overlays/prod/topology-spread.yaml"] = f"""\
- op: add
  path: /spec/template/spec/topologySpreadConstraints
  value:
    - maxSkew: 1
      topologyKey: kubernetes.io/hostname
      whenUnsatisfiable: ScheduleAnyway
      labelSelector:
        matchLabels:
          app.kubernetes.io/instance: {ir.name}
"""
    return output
