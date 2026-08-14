# 部署指南

CLI 的 `render` 命令只生成文件，不连接 Docker daemon 或 Kubernetes API。检查生成内容后再显式部署。

## Docker Compose

```bash
jina-serving render compose --config serving.yaml --output build/compose
docker compose -f build/compose/compose.yaml config
docker compose -f build/compose/compose.yaml up -d
```

如系统安装的是独立命令，可使用 `docker-compose`。

combined bundle 包含：

- 私有 `embedding` 服务；
- 私有 `reranker` 服务；
- 唯一发布主机端口的无特权 Nginx gateway；
- gateway 的本地只读配置文件。

Compose 不提供 Kubernetes 等级的调度、滚动升级和弹性伸缩，不应把单机验证结果当作高可用生产证明。

## Helm

```bash
jina-serving render helm --config serving.yaml --output build/helm
helm lint build/helm -f build/helm/values.generated.yaml
helm template search-models build/helm \
  -f build/helm/values.generated.yaml \
  --namespace ai-serving

helm upgrade --install search-models build/helm \
  -f build/helm/values.generated.yaml \
  --namespace ai-serving \
  --create-namespace
```

Chart 包含 Deployment、Service、ServiceAccount、startup/readiness/liveness probes、security context、NetworkPolicy、按副本数生成的 PDB，以及 combined gateway。Ingress 默认关闭，因为域名、IngressClass、TLS Secret 和认证属于环境配置。

## Kustomize

Kustomize bundle 复用相同 Helm Chart，避免两套 workload 模板漂移。构建时必须显式启用 Helm generator：

```bash
jina-serving render kustomize --config serving.yaml --output build/kustomize

kustomize build --enable-helm build/kustomize/base
kustomize build --enable-helm build/kustomize/overlays/dev
kustomize build --enable-helm build/kustomize/overlays/prod
```

也可以使用：

```bash
kubectl kustomize build/kustomize/overlays/prod --enable-helm
```

部署前保存并审查最终 YAML：

```bash
kustomize build --enable-helm build/kustomize/overlays/prod > rendered.yaml
kubectl apply --server-side --dry-run=server -f rendered.yaml
kubectl apply --server-side -f rendered.yaml
```

`dry-run=server` 和真实 `apply` 会访问当前 Kubernetes context，必须由操作者在确认集群后执行。

## 生产镜像固定

生产配置应对每个模型设置 `image.digest`，并将 `exposure.gatewayImage` 写成完整 digest 引用，然后启用：

```yaml
production:
  requireImageDigest: true
```

离线环境还需要提前把这些 digest 对应镜像同步到内部 registry 或加载到每个节点；renderer 不负责传输镜像。

## 验证层级

1. `jina-serving validate`：Schema、catalog 和 IR。
2. `docker compose config`、`helm lint/template`、`kustomize build`：静态部署产物。
3. CPU 镜像 API smoke：真实 `/health`、`/v1/embeddings` 或 `/v1/rerank`。
4. GPU smoke：NVIDIA runtime、显存、并发和输出正确性。
5. Kubernetes smoke：调度、探针、NetworkPolicy、滚动升级和真实入口。

各层必须单独记录，不能互相替代。
