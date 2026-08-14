#!/usr/bin/env bash

set -euo pipefail

readonly role="${1:-}"
readonly image_ref="${2:-}"
readonly runtime="${3:-cpu}"
readonly timeout_seconds="${SMOKE_TIMEOUT_SECONDS:-600}"
readonly container_name="jina-serving-smoke-$$-${RANDOM}"

if [[ "${role}" != "embedding" && "${role}" != "reranker" ]]; then
  echo "usage: $0 <embedding|reranker> <local-image-reference> [cpu|gpu]" >&2
  exit 2
fi
if [[ -z "${image_ref}" ]]; then
  echo "image reference is required" >&2
  exit 2
fi
if [[ "${runtime}" != "cpu" && "${runtime}" != "gpu" ]]; then
  echo "runtime must be cpu or gpu" >&2
  exit 2
fi
if [[ ! "${timeout_seconds}" =~ ^[1-9][0-9]*$ ]]; then
  echo "SMOKE_TIMEOUT_SECONDS must be a positive integer" >&2
  exit 2
fi
if ! docker image inspect "${image_ref}" >/dev/null 2>&1; then
  echo "image is not available locally; pull or load it explicitly first: ${image_ref}" >&2
  exit 1
fi

cleanup() {
  if docker container inspect "${container_name}" >/dev/null 2>&1; then
    docker stop --time 30 "${container_name}" >/dev/null
  fi
}
trap cleanup EXIT

docker_args=(
  run
  --detach
  --rm
  --name "${container_name}"
  --user 65534:65534
  --read-only
  --tmpfs /tmp:rw,nosuid,nodev,size=1g
  --cap-drop ALL
  --security-opt no-new-privileges
  --publish 127.0.0.1::8080
)
if [[ "${runtime}" == "gpu" ]]; then
  docker_args+=(--gpus all)
fi
docker_args+=("${image_ref}")

docker "${docker_args[@]}" >/dev/null

port_mapping="$(docker port "${container_name}" 8080/tcp)"
host_port="${port_mapping##*:}"
base_url="http://127.0.0.1:${host_port}"
deadline="$((SECONDS + timeout_seconds))"

until curl --fail --silent --show-error "${base_url}/health" >/dev/null; do
  if ((SECONDS >= deadline)); then
    docker logs "${container_name}" >&2
    echo "model did not become healthy within ${timeout_seconds}s" >&2
    exit 1
  fi
  sleep 5
done

if [[ "${role}" == "embedding" ]]; then
  request='{"input":["hello world"]}'
  endpoint="/v1/embeddings"
else
  request='{"query":"best model","documents":["first document","best model"]}'
  endpoint="/v1/rerank"
fi

response="$(curl --fail --silent --show-error \
  --header 'Content-Type: application/json' \
  --data "${request}" \
  "${base_url}${endpoint}")"

python - "${role}" "${response}" <<'PY'
import json
import sys

role = sys.argv[1]
payload = json.loads(sys.argv[2])
required = "data" if role == "embedding" else "results"
if not isinstance(payload.get(required), list) or not payload[required]:
    raise SystemExit(f"response does not contain a non-empty {required!r} list")
print(f"{role} smoke passed: {required}={len(payload[required])}")
PY
