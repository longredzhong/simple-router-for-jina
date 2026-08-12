# simple-router-for-jina

Single-file model routing gateway for [jina-on-prem](https://github.com/jina-ai/jina-on-prem)
style model services. One entry point, many backends: a request is routed to
the right embedding / reranker / chat service purely by the model id it carries
(OpenAI body field or Gemini URL path), and `docker-compose.yml` is generated
from a tiny TOML file you actually want to edit.

- **One Python file, three jobs** — `serve` (routing gateway), `compose`
  (docker-compose generator), `init`/`list` (config scaffolding & catalog).
  Dependencies: `click` and `requests` only; TOML via stdlib `tomllib`.
- **Image info lives in code** — the model catalog is embedded; you never
  type an image name. `runtime = "gpu"` picks the `:gpu` image tag and adds
  `gpus: all` automatically.
- **Compose-native scaling** — `replicas = N` per model; Docker DNS
  round-robins across replicas behind the single router entry.
- **Streaming pass-through** — SSE / chunked responses are relayed
  chunk-by-chunk, so chat-style streaming works end to end.
- **Production error paths** — 404 unknown model, 502 unreachable backend
  (with retries), 504 timeout, 413 oversized body, degraded `/health` probing.

## Install

```bash
pip install simple-router-for-jina
```

or run the file directly (no install needed), which is also how it ships in
Docker:

```bash
python simple-router.py --help
```

## Quick start

```bash
python simple-router.py init                 # write a starter router.toml
python simple-router.py list                 # show the built-in model catalog
python simple-router.py compose --config router.toml --out-dir deploy
```

This writes `deploy/docker-compose.yml` (one service per enabled model plus
the `router` entry) and `deploy/router-config.json` (the runtime routing
table). Bring it up with:

```bash
docker compose -f deploy/docker-compose.yml up -d

curl http://localhost:8080/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"model": "jina-embeddings-v3", "input": ["hello world"]}'

curl http://localhost:8080/v1/rerank \
  -H 'Content-Type: application/json' \
  -d '{"model": "jina-reranker-v3", "query": "best model", "documents": ["a", "b"], "top_n": 2}'
```

There is no deploy without Docker either:

```bash
python simple-router.py serve --config router.toml
```

## CLI

| Command | Description |
|---|---|
| `init [--output FILE]` | Write a commented starter `router.toml` |
| `list [--config FILE]` | Show the embedded model catalog (cpu/gpu images), `*` = enabled in config |
| `compose --config FILE [--out-dir DIR] [--stdout] [--port N]` | Generate `docker-compose.yml` + `router-config.json` |
| `serve --config FILE [--port N] [--host H] [--check-backends] [--verbose]` | Run the routing gateway |

## Configuration

A single TOML file is the whole deployment definition. Models are enabled by
adding a `[models.<id>]` section; every other field is optional.

```toml
host = "0.0.0.0"
port = 8080
default_model = "jina-embeddings-v3"   # used when a request carries no model

[models.jina-embeddings-v3]
replicas = 2
runtime = "gpu"                        # cpu | gpu; image tag follows
env = { JINA_DTYPE = "float32" }

[models.jina-reranker-v3]
replicas = 1
```

| Field | Default | Meaning |
|---|---|---|
| `host` / `port` | `0.0.0.0` / `8080` | router listen address |
| `default_model` | `null` | fallback when the request has no model id |
| `timeout` / `connect_timeout` | `300` / `5` | backend read / connect seconds |
| `retries` | `1` | reconnect attempts on connection errors |
| `max_body_mb` | `64` | request body limit (413 beyond) |
| `project` / `router_image` / `router_build` | — | compose project name, router image / build context |
| `[models.<id>] enabled` | `true` | `false` = keep the section, do not deploy |
| `replicas` | `1` | instances; compose load-balances via DNS |
| `runtime` | `cpu` | picks the image tag and `gpus: all` |
| `cpus` / `memory` | from catalog | resource limits |
| `port` | `8080` | container port of the model image |
| `env` | — | extra environment variables |
| `aliases` | — | extra model ids the router will accept |
| `image` | from catalog | override for custom backends (see below) |
| `healthcheck` | `true` | container healthcheck (python urllib) |

### Model catalog

The catalog of 8 models (embeddings v5 nano/small, v3, omni nano/small,
clip-v2, rerankers v3/v3.5) with images, CPU/GPU runtime hints and resource
defaults is embedded in the code — run `list` to see it. [jina-on-prem](https://github.com/jina-ai/jina-on-prem)
prebuilt images are used as-is.

### Custom backends

Any id outside the catalog works if you give it an `image` — useful for
self-built or third-party services (vLLM, local rerankers, ...):

```toml
[models.my-llm]
image = "ghcr.io/me/llm:v1"
runtime = "gpu"
base_url = "http://10.0.0.5:8080"     # advanced: override the derived URL
```

## How routing works

- OpenAI / Cohere style: the `model` field of the JSON body
  (`/v1/embeddings`, `/v1/rerank`, `/v1/chat/completions`, `/v2/embed`, ...).
- Gemini style: the id embedded in the URL (`/v1/models/{model}:embedContent`).
- Matching order: exact id → aliases → `default_model`.
- `GET /health` (probes backends with `--check-backends`), `GET /v1/models`,
  `GET /list`, and `GET /_config` (internal) are served by the router itself.
- Responses — including SSE streams — are relayed with status and headers
  intact; errors map to 404 / 413 / 502 / 504.

## Publishing to PyPI

### Automatic (GitHub Actions)

`.github/workflows/publish.yml` builds the sdist + wheel and publishes with
Trusted Publishing (OIDC) on every GitHub Release (`published` event) or
manually via `workflow_dispatch`.

Setup once on PyPI: **Publishing > Trusted Publishers**, add a pending
publisher with your GitHub repo / `main` branch / `publish` workflow name.

### Local

```bash
pixi add --pypi build twine        # or: python -m pip install build twine
pixi run build                     # python -m build  -> dist/*
pixi run check                     # twine check dist/*
pixi run publish                   # twine upload dist/*   (+ --repository testpypi for a dry run)
```

## Development

```bash
pixi install
pixi run python simple-router.py --help
```

## Roadmap

- Generate Kubernetes manifests (Deployment + Service + HPA + Ingress) from
  the same TOML definition, letting `replicas`/`resources` map to HPA
  min/max/limits.

## License

MIT