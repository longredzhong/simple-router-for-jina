"""Docker Compose renderer."""

from __future__ import annotations

from typing import Any

import yaml

from simple_router_for_jina.compiler import DeploymentIR, ServiceIR
from simple_router_for_jina.config.schema import ExposureMode


def _compose_memory(quantity: str) -> str:
    value = int(quantity[:-2])
    suffix = quantity[-2:]
    if suffix == "Ti":
        return f"{value * 1024}g"
    return f"{value}{'g' if suffix == 'Gi' else 'm'}"


def _logging() -> dict[str, Any]:
    return {
        "driver": "json-file",
        "options": {"max-size": "10m", "max-file": "3"},
    }


def _model_service(service: ServiceIR, *, publish_port: int | None) -> dict[str, Any]:
    limits: dict[str, Any] = {
        "cpus": service.resources.cpu,
        "memory": _compose_memory(service.resources.memory),
    }
    resources: dict[str, Any] = {"limits": limits}
    if service.resources.gpu:
        resources["reservations"] = {
            "devices": [
                {
                    "driver": "nvidia",
                    "count": service.resources.gpu,
                    "capabilities": ["gpu"],
                }
            ]
        }

    result: dict[str, Any] = {
        "image": service.image,
        "restart": "unless-stopped",
        "init": True,
        "user": "65534:65534",
        "read_only": True,
        "tmpfs": ["/tmp:rw,nosuid,nodev,size=1g"],
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "stop_grace_period": "60s",
        "expose": [str(service.container_port)],
        "healthcheck": {
            "test": ["CMD", "curl", "-fsS", f"http://localhost:{service.container_port}/health"],
            "interval": "15s",
            "timeout": "5s",
            "start_period": "120s",
            "retries": 5,
        },
        "deploy": {"replicas": service.replicas, "resources": resources},
        "logging": _logging(),
    }
    if service.env:
        result["environment"] = dict(service.env)
    if publish_port is not None:
        result["ports"] = [f"{publish_port}:{service.container_port}"]
    return result


def _gateway_service(ir: DeploymentIR) -> dict[str, Any]:
    return {
        "image": ir.gateway_image,
        "restart": "unless-stopped",
        "init": True,
        "user": "101:101",
        "read_only": True,
        "tmpfs": [
            "/tmp:rw,nosuid,nodev,size=64m",
            "/var/cache/nginx:rw,nosuid,nodev,size=64m",
            "/var/run:rw,nosuid,nodev,size=8m",
        ],
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "stop_grace_period": "30s",
        "ports": [f"{ir.exposure_port}:8080"],
        "volumes": ["./gateway/nginx.conf:/etc/nginx/conf.d/default.conf:ro"],
        "depends_on": {service.role: {"condition": "service_healthy"} for service in ir.services},
        "healthcheck": {
            "test": ["CMD", "wget", "-qO-", "http://localhost:8080/health"],
            "interval": "15s",
            "timeout": "5s",
            "start_period": "10s",
            "retries": 3,
        },
        "logging": _logging(),
    }


def _gateway_config() -> str:
    return """\
resolver 127.0.0.11 ipv6=off valid=10s;

server {
    listen 8080;
    server_name _;
    client_max_body_size 64m;

    proxy_http_version 1.1;
    proxy_connect_timeout 5s;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
    proxy_request_buffering off;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection "";

    location = /health {
        access_log off;
        default_type application/json;
        return 200 '{"status":"ok"}';
    }

    location = /v1/rerank {
        set $reranker_upstream http://reranker:8080;
        proxy_pass $reranker_upstream;
    }

    location = /v1/embeddings {
        set $embedding_upstream http://embedding:8080;
        proxy_pass $embedding_upstream;
    }

    location = /v2/embed {
        set $embedding_upstream http://embedding:8080;
        proxy_pass $embedding_upstream;
    }

    location = /v1/models {
        set $embedding_upstream http://embedding:8080;
        proxy_pass $embedding_upstream;
    }

    location /v1/models/ {
        set $embedding_upstream http://embedding:8080;
        proxy_pass $embedding_upstream;
    }

    location = /v1/classify {
        set $embedding_upstream http://embedding:8080;
        proxy_pass $embedding_upstream;
    }

    location / {
        default_type application/json;
        return 404 '{"error":{"message":"unsupported endpoint","code":"not_found"}}';
    }
}
"""


def render_compose(ir: DeploymentIR) -> dict[str, str]:
    """Render a movable Docker Compose bundle."""

    services: dict[str, Any] = {}
    direct = ir.exposure_mode is ExposureMode.DIRECT
    for service in ir.services:
        services[service.role] = _model_service(
            service,
            publish_port=ir.exposure_port if direct else None,
        )
    output: dict[str, str] = {}
    if ir.exposure_mode is ExposureMode.GATEWAY:
        services["gateway"] = _gateway_service(ir)
        output["gateway/nginx.conf"] = _gateway_config()

    compose = {
        "name": ir.name,
        "services": services,
    }
    output["compose.yaml"] = yaml.safe_dump(compose, sort_keys=False, width=100)
    return output
