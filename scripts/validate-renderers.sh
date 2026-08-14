#!/usr/bin/env bash

set -euo pipefail

readonly project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly validation_dir="$(mktemp -d)"

cleanup() {
  if [[ -n "${validation_dir}" && -d "${validation_dir}" ]]; then
    rm -rf -- "${validation_dir}"
  fi
}
trap cleanup EXIT

cd "${project_root}"

if docker compose version >/dev/null 2>&1; then
  compose_command=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  compose_command=(docker-compose)
else
  echo "Docker Compose is required for renderer validation" >&2
  exit 1
fi

if ! command -v helm >/dev/null 2>&1; then
  echo "Helm is required for renderer validation" >&2
  exit 1
fi

build_kustomize() {
  local source_dir="$1"
  if command -v kustomize >/dev/null 2>&1; then
    kustomize build --enable-helm "${source_dir}"
  elif command -v kubectl >/dev/null 2>&1; then
    kubectl kustomize "${source_dir}" --enable-helm
  else
    echo "Kustomize or kubectl is required for renderer validation" >&2
    return 1
  fi
}

for mode in embedding reranker combined; do
  config="examples/${mode}.yaml"

  uv run jina-serving render compose \
    --config "${config}" \
    --output "${validation_dir}/${mode}/compose"
  "${compose_command[@]}" \
    -f "${validation_dir}/${mode}/compose/compose.yaml" \
    config --quiet

  uv run jina-serving render helm \
    --config "${config}" \
    --output "${validation_dir}/${mode}/helm"
  helm lint "${validation_dir}/${mode}/helm" \
    -f "${validation_dir}/${mode}/helm/values.generated.yaml" >/dev/null
  helm template "${mode}-validation" "${validation_dir}/${mode}/helm" \
    -f "${validation_dir}/${mode}/helm/values.generated.yaml" \
    --namespace ai-serving >/dev/null

  uv run jina-serving render kustomize \
    --config "${config}" \
    --output "${validation_dir}/${mode}/kustomize"
  for layer in base overlays/dev overlays/prod; do
    build_kustomize "${validation_dir}/${mode}/kustomize/${layer}" >/dev/null
  done
done

uv run jina-serving render compose \
  --config examples/embedding-secret.yaml \
  --output "${validation_dir}/secret/compose"
JINA_LICENSE_KEY=validation-placeholder \
  "${compose_command[@]}" \
  -f "${validation_dir}/secret/compose/compose.yaml" \
  config --quiet

echo "renderer validation passed"
