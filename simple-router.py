#!/usr/bin/env python3
"""
simple-router: single-file model router + deploy generator for jina-on-prem.

One file, two jobs, driven by one small TOML config:

  1. `serve`   - run the routing gateway (reverse proxy). Model id is taken
                 from the JSON body `model` field (OpenAI/Cohere style) or the
                 URL path (Gemini style /v1/models/{model}:embedContent) and
                 the request is forwarded to the matching backend. SSE /
                 streaming responses pass through chunk-by-chunk.
  2. `compose` - generate docker-compose.yml + router-config.json from the
                 same TOML: one service per enabled model + the router entry.

Model image info lives in MODEL_CATALOG below - users only pick model ids and
tune replicas/resources in a TOML file, they never touch image names.

Dependencies: click + requests. TOML is parsed with stdlib tomllib.

Usage:
    python simple-router.py init                      # write a starter router.toml
    python simple-router.py list                      # show the model catalog
    python simple-router.py compose --config router.toml --out-dir deploy
    python simple-router.py serve --config router.toml

Docker (the compose file mounts the TOML into the router image):
    docker compose -f deploy/docker-compose.yml up -d
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

import click
import requests

log = logging.getLogger("simple-router")

# ---------------------------------------------------------------------------
# embedded model catalog: image info + sane defaults. `runtime` can be
# overridden to "gpu" per model in the TOML (image tag follows automatically).
# ---------------------------------------------------------------------------

IMAGE_TEMPLATE = "ghcr.io/jina-ai/jina-on-prem/{model}:{runtime}"

MODEL_CATALOG: dict[str, dict] = {
    # embeddings
    "jina-embeddings-v5-text-nano": {
        "type": "embedding", "runtime": "cpu", "port": 8080,
        "cpus": 2, "memory": "4g", "env": {}},
    "jina-embeddings-v5-text-small": {
        "type": "embedding", "runtime": "cpu", "port": 8080,
        "cpus": 4, "memory": "6g", "env": {}},
    "jina-embeddings-v3": {
        "type": "embedding", "runtime": "cpu", "port": 8080,
        "cpus": 4, "memory": "6g", "env": {}},
    "jina-embeddings-v5-omni-nano": {
        "type": "embedding", "runtime": "cpu", "port": 8080,
        "cpus": 4, "memory": "8g", "env": {}},
    "jina-embeddings-v5-omni-small": {
        "type": "embedding", "runtime": "cpu", "port": 8080,
        "cpus": 8, "memory": "16g", "env": {}},
    "jina-clip-v2": {
        "type": "embedding", "runtime": "cpu", "port": 8080,
        "cpus": 4, "memory": "8g", "env": {}},
    # rerankers
    "jina-reranker-v3.5": {
        "type": "reranker", "runtime": "cpu", "port": 8080,
        "cpus": 4, "memory": "6g", "env": {}},
    "jina-reranker-v3": {
        "type": "reranker", "runtime": "cpu", "port": 8080,
        "cpus": 4, "memory": "6g", "env": {}},
}

ROUTER_DEFAULTS = {
    "host": "0.0.0.0",
    "port": 8080,
    "default_model": None,
    "timeout": 300,
    "connect_timeout": 5,
    "retries": 1,
    "max_body_mb": 64,
    "project": "simple-router-for-jina",
    "router_image": "simple-router-for-jina/router:0.1.0",
    "router_build": ".",
    "check_backends": False,
}

INIT_TEMPLATE = """\
# simple-router-for-jina - deployment definition.
# Images are built into the code; here you only pick models and tune resources.
# Run `simple-router.py list` to see every available model id.

host = "0.0.0.0"
port = 8080
# default_model = "jina-embeddings-v3"   # used when a request carries no model
# timeout = 300
# connect_timeout = 5
# retries = 1
# max_body_mb = 64

# Router container image (used by `compose` only)
# project = "simple-router-for-jina"
# router_image = "simple-router-for-jina/router:0.1.0"
# router_build = "."

# Each section enables one model backend. Supported fields (all optional):
#   enabled = false    # keep the section but don't deploy
#   replicas = 2       # instances; compose load-balances across them
#   runtime = "gpu"    # cpu | gpu - image tag follows automatically
#   cpus = 4           # resource limit
#   memory = "8g"      # resource limit
#   port = 8080        # container port
#   env = { KEY = "value" }
#   aliases = ["other-name"]      # extra ids accepted by the router
#   healthcheck = false           # disable container healthcheck
[models.jina-embeddings-v3]
replicas = 2

[models.jina-reranker-v3]
replicas = 1
"""

# /v1/models/{model}:embedContent  (Gemini style, model id lives in the path)
MODEL_IN_PATH = re.compile(r"^/v1/models/([^/:]+)")

# hop-by-hop headers that must not be forwarded
HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "host",
    "content-length", "expect",
})


# ---------------------------------------------------------------------------
# config: TOML -> merged deployment definition
# ---------------------------------------------------------------------------

def sanitize_service_name(name: str) -> str:
    """docker compose service names allow [a-zA-Z0-9._-]"""
    return re.sub(r"[^a-zA-Z0-9._-]", "-", name)


def load_deployment(config_path: str) -> dict:
    with open(config_path, "rb") as fh:
        data = tomllib.load(fh)

    router = {k: data.get(k, v) for k, v in ROUTER_DEFAULTS.items()}

    models = []
    for mid, overrides in (data.get("models") or {}).items():
        if overrides.get("enabled") is False:
            continue
        if mid in MODEL_CATALOG:
            m = {**MODEL_CATALOG[mid], **overrides}
            m["runtime"] = overrides.get("runtime", MODEL_CATALOG[mid]["runtime"])
            m["image"] = overrides.get("image") or IMAGE_TEMPLATE.format(
                model=mid, runtime=m["runtime"])
        elif "image" in overrides:
            # custom backend: not in the catalog, must give an explicit image
            m = {"type": "custom", "runtime": "cpu", "port": 8080,
                 "cpus": 2, "memory": "4g", "env": {}, **overrides}
            m["runtime"] = overrides.get("runtime", "cpu")
            m["image"] = overrides["image"]
        else:
            raise click.ClickException(
                f"unknown model {mid!r}; it is not in the catalog and no "
                f"`image` was given (see `list` for the catalog)")
        if m["runtime"] not in ("cpu", "gpu"):
            raise click.ClickException(f"model {mid!r}: runtime must be cpu|gpu")
        m["id"] = mid
        m.setdefault("aliases", [])
        m.setdefault("replicas", 1)
        m.setdefault("healthcheck", True)
        m.setdefault("base_url", None)
        models.append(m)

    if not models:
        raise click.ClickException("no models enabled in config")
    return {"router": router, "models": models}


def build_router_config(deployment: dict) -> dict:
    router = deployment["router"]
    models = []
    for m in deployment["models"]:
        svc = sanitize_service_name(m["id"])
        models.append({
            "id": m["id"],
            "aliases": m.get("aliases", []),
            "base_url": m.get("base_url") or f"http://{svc}:{m['port']}",
        })
    return {
        "host": router["host"],
        "port": router["port"],
        "default_model": router["default_model"],
        "timeout": router["timeout"],
        "connect_timeout": router["connect_timeout"],
        "retries": router["retries"],
        "max_body_mb": router["max_body_mb"],
        "models": models,
    }


# ---------------------------------------------------------------------------
# gateway (`serve`)
# ---------------------------------------------------------------------------

class Router:
    def __init__(self, router_cfg: dict):
        self.cfg = router_cfg
        self.default_model = router_cfg.get("default_model")
        self.routes: dict[str, str] = {}
        self.model_ids: list[str] = []
        for m in router_cfg["models"]:
            base_url = m["base_url"].rstrip("/")
            self.routes[m["id"]] = base_url
            for alias in m.get("aliases", []):
                self.routes[alias] = base_url
            self.model_ids.append(m["id"])
        self.session = requests.Session()

    def resolve(self, model: str) -> str | None:
        return self.routes.get(model)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "simple-router/0.1"
    sys_version = ""

    @property
    def router(self) -> Router:
        return self.server.router

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    def _send_json(self, status: int, obj: dict):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str, code: str = "internal_error"):
        self._send_json(status, {
            "error": {"message": message, "type": "invalid_request_error",
                      "code": code}})

    def _read_body(self) -> bytes | None:
        if self.command in ("GET", "HEAD", "OPTIONS"):
            return b""
        if self.headers.get("Expect", "").lower() == "100-continue":
            self.wfile.write(b"HTTP/1.1 100 Continue\r\n\r\n")
            self.wfile.flush()
        raw_len = self.headers.get("Content-Length")
        if raw_len is None:
            return None
        length = int(raw_len)
        max_bytes = self.router.cfg["max_body_mb"] * 1024 * 1024
        if length > max_bytes:
            self._error(413, f"request body too large (limit {max_bytes} bytes)",
                        "payload_too_large")
            return None
        return self.rfile.read(length)

    def _extract_model(self, path: str, body: bytes) -> str | None:
        m = MODEL_IN_PATH.search(path)
        if m:
            return unquote(m.group(1))
        if body:
            try:
                data = json.loads(body)
            except (ValueError, TypeError):
                data = None
            if isinstance(data, dict) and isinstance(data.get("model"), str):
                return data["model"]
        return None

    def _forward(self, path: str):
        parsed = urlparse(path)
        body = self._read_body()
        if body is None:
            return  # 413 already sent

        # ---- control plane endpoints (never proxied) ----
        if self.command == "GET":
            if parsed.path in ("/health", "/"):
                self._health()
                return
            if parsed.path == "/v1/models":
                self._send_json(200, {
                    "object": "list",
                    "data": [{"id": mid, "object": "model",
                              "owned_by": "simple-router-for-jina"}
                             for mid in self.router.model_ids]})
                return
            if parsed.path == "/list":
                self._send_json(200, {
                    "default_model": self.router.default_model,
                    "routes": {mid: self.router.routes[mid]
                               for mid in self.router.model_ids}})
                return

        model = self._extract_model(parsed.path, body)
        if model is None:
            model = self.router.default_model
        base_url = self.router.resolve(model) if model else None
        if base_url is None:
            self._error(404, f"unknown model: {model!r}", "model_not_found")
            return

        target = base_url + parsed.path
        if parsed.query:
            target += "?" + parsed.query

        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in HOP_BY_HOP}
        if body:
            headers.setdefault("Content-Type", "application/json")

        cfg = self.router.cfg
        timeout = (cfg["connect_timeout"], cfg["timeout"])
        response = None
        started = time.monotonic()
        for attempt in range(cfg["retries"] + 1):
            try:
                response = self.router.session.request(
                    self.command, target, headers=headers, data=body,
                    stream=True, timeout=timeout)
                break
            except requests.ConnectionError:
                if attempt < cfg["retries"]:
                    time.sleep(0.2 * (attempt + 1))
                    continue
                self._error(502, f"cannot reach backend for model {model!r}: "
                                 f"{base_url}", "backend_unreachable")
                return
            except requests.Timeout:
                self._error(504, f"backend timeout for model {model!r}",
                            "backend_timeout")
                return
            except requests.RequestException as exc:
                self._error(502, f"backend error for model {model!r}: {exc}",
                            "backend_error")
                return

        # ---- relay status + headers, stream the body ----
        self.send_response(response.status_code)
        for k, v in response.headers.items():
            if k.lower() not in HOP_BY_HOP:
                self.send_header(k, v)
        self.send_header("Connection", "close")
        self.end_headers()

        total = 0
        try:
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                self.wfile.write(chunk)
                self.wfile.flush()
                total += len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            response.close()
        log.info("route %s %s model=%s -> %s status=%s bytes=%s %.0fms",
                 self.command, parsed.path, model, base_url,
                 response.status_code, total,
                 (time.monotonic() - started) * 1000)

    def _health(self):
        if not self.server.check_backends:
            self._send_json(200, {"status": "ok", "models": self.router.model_ids})
            return
        results = {}
        healthy = True
        for mid in self.router.model_ids:
            try:
                r = self.router.session.get(
                    self.router.routes[mid] + "/health",
                    timeout=self.router.cfg["connect_timeout"])
                results[mid] = r.status_code == 200
            except requests.RequestException:
                results[mid] = False
            healthy = healthy and results[mid]
        self._send_json(200 if healthy else 503,
                        {"status": "ok" if healthy else "degraded",
                         "backends": results})

    def do_GET(self):
        self._forward(self.path)

    def do_POST(self):
        self._forward(self.path)

    def do_PUT(self):
        self._forward(self.path)

    def do_PATCH(self):
        self._forward(self.path)

    def do_DELETE(self):
        self._forward(self.path)

    def do_OPTIONS(self):
        self._send_json(200, {"status": "ok"})


def run_serve(router_cfg: dict, check_backends: bool, verbose: bool):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    router = Router(router_cfg)
    server = ThreadingHTTPServer((router_cfg["host"], router_cfg["port"]),
                                 Handler)
    server.router = router
    server.check_backends = check_backends
    log.info("listening on %s:%d, %d model(s), default=%r",
             router_cfg["host"], router_cfg["port"], len(router.model_ids),
             router.default_model)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        router.session.close()


# ---------------------------------------------------------------------------
# compose generator
# ---------------------------------------------------------------------------

def yaml_scalar(value) -> str:
    """strings double-quoted via json.dumps (valid YAML), others bare"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def build_compose_yaml(deployment: dict, config_path: str) -> str:
    router = deployment["router"]
    lines = [f"name: {yaml_scalar(router['project'])}", "services:"]

    for m in deployment["models"]:
        svc = sanitize_service_name(m["id"])
        lines.append(f"  {svc}:")
        lines.append(f"    image: {yaml_scalar(m['image'])}")
        lines.append("    restart: unless-stopped")
        if m["runtime"] == "gpu":
            lines.append("    gpus: all")
        lines.append("    deploy:")
        lines.append(f"      replicas: {int(m.get('replicas', 1))}")
        lines.append("      resources:")
        lines.append("        limits:")
        lines.append(f"          cpus: {yaml_scalar(m.get('cpus', 2))}")
        lines.append(f"          memory: {yaml_scalar(m.get('memory', '4g'))}")
        if m.get("env"):
            lines.append("    environment:")
            for k, v in m["env"].items():
                lines.append(f"      {k}: {yaml_scalar(v)}")
        if m.get("healthcheck", True):
            lines.append("    healthcheck:")
            probe = f"import urllib.request as u;u.urlopen('http://localhost:{m['port']}/health')"
            lines.append(f"      test: [\"CMD\", \"python\", \"-c\", {json.dumps(probe)}]")
            lines.append("      interval: 30s")
            lines.append("      timeout: 5s")
            lines.append("      start_period: 60s")
            lines.append("      retries: 3")

    lines.append("  router:")
    if router.get("router_build"):
        lines.append(f"    build: {yaml_scalar(router['router_build'])}")
    if router.get("router_image"):
        lines.append(f"    image: {yaml_scalar(router['router_image'])}")
    lines.append("    restart: unless-stopped")
    lines.append(f"    ports:")
    lines.append(f'      - "{router["port"]}:{router["port"]}"')
    lines.append("    volumes:")
    mount = config_path if os.path.isabs(config_path) else "./" + config_path
    lines.append(f'      - "{mount}:/app/config.toml:ro"')
    lines.append("    depends_on:")
    for m in deployment["models"]:
        lines.append(f"      - {sanitize_service_name(m['id'])}")
    lines.append("    healthcheck:")
    probe = f"import urllib.request as u;u.urlopen('http://localhost:{router['port']}/health')"
    lines.append(f"      test: [\"CMD\", \"python\", \"-c\", {json.dumps(probe)}]")
    lines.append("      interval: 30s")
    lines.append("      timeout: 5s")
    lines.append("      start_period: 10s")
    lines.append("      retries: 3")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """simple-router: model router + deploy generator for jina-on-prem."""


@cli.command(help="Write a starter router.toml to get you going.")
@click.option("--output", default="router.toml", type=click.Path(dir_okay=False),
              show_default=True)
def init(output):
    if os.path.exists(output):
        raise click.ClickException(f"{output} already exists")
    with open(output, "w", encoding="utf-8") as fh:
        fh.write(INIT_TEMPLATE)
    click.echo(f"wrote {output} - edit it, then run "
               f"`compose` or `serve` with --config {output}")


@cli.command(name="list", help="Show the built-in model catalog "
                               "(image info lives in code).")
@click.option("--config", type=click.Path(exists=True, dir_okay=False),
              default=None, help="mark models enabled in this config with *")
def list_models(config):
    enabled = set()
    if config:
        try:
            enabled = {m["id"] for m in load_deployment(config)["models"]}
        except click.ClickException as exc:
            click.echo(f"warning: {exc}", err=True)
    click.echo(f"{'ID':<32} {'TYPE':<10} IMAGE (cpu / gpu)")
    for mid, m in MODEL_CATALOG.items():
        mark = "*" if mid in enabled else " "
        cpu = IMAGE_TEMPLATE.format(model=mid, runtime="cpu")
        gpu = IMAGE_TEMPLATE.format(model=mid, runtime="gpu")
        click.echo(f"{mark}{mid:<31} {m['type']:<10} {cpu} / {gpu}")
    if config:
        click.echo("\n* = enabled in config")


@cli.command(help="Generate docker-compose.yml + router-config.json from TOML.")
@click.option("--config", required=True, type=click.Path(exists=True,
                                                         dir_okay=False),
              help="deployment definition (TOML)")
@click.option("--out-dir", type=click.Path(file_okay=False), default=None,
              help="write compose + router-config here (default: print)")
@click.option("--stdout", is_flag=True, help="print docker-compose.yml only")
@click.option("--port", type=int, default=None, help="override router port")
def compose(config, out_dir, stdout, port):
    deployment = load_deployment(config)
    if port:
        deployment["router"]["port"] = port
    router_cfg = build_router_config(deployment)
    yaml_out = build_compose_yaml(deployment, config)

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "docker-compose.yml"), "w",
                  encoding="utf-8") as fh:
            fh.write(yaml_out)
        with open(os.path.join(out_dir, "router-config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(router_cfg, fh, indent=2)
            fh.write("\n")
        click.echo(f"wrote {os.path.join(out_dir, 'docker-compose.yml')}")
        click.echo(f"wrote {os.path.join(out_dir, 'router-config.json')}")
        click.echo(f"next: docker compose -f "
                   f"{os.path.join(out_dir, 'docker-compose.yml')} up -d")
    elif stdout:
        click.echo(yaml_out)
    else:
        click.echo("use --out-dir DIR to write files, or --stdout to print")


@cli.command(help="Run the routing gateway.")
@click.option("--config", required=True, type=click.Path(exists=True,
                                                         dir_okay=False),
              help="deployment definition (TOML)")
@click.option("--port", type=int, default=None, help="override listen port")
@click.option("--host", default=None, help="override listen host")
@click.option("--check-backends", is_flag=True, default=None,
              help="probe every backend on /health")
@click.option("--verbose", is_flag=True)
def serve(config, port, host, check_backends, verbose):
    deployment = load_deployment(config)
    router_cfg = build_router_config(deployment)
    if port:
        router_cfg["port"] = port
    if host:
        router_cfg["host"] = host
    if check_backends is None:
        check_backends = deployment["router"]["check_backends"]
    run_serve(router_cfg, check_backends, verbose)


if __name__ == "__main__":
    sys.exit(cli())
