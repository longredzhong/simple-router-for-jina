# 配置参考

## 顶层结构

规范输入为 YAML：

```yaml
apiVersion: serving.jina.ai/v1alpha1
kind: JinaServing
metadata:
  name: search-models
  namespace: ai-serving
spec:
  mode: combined
```

未知字段会被拒绝。可以通过以下命令导出机器可读 Schema：

```bash
jina-serving schema --output jina-serving.schema.json
```

## metadata

| 字段 | 必需 | 说明 |
|---|---:|---|
| `name` | 是 | 小写 DNS label，作为 Compose project 和 Kubernetes 资源名前缀。 |
| `namespace` | 否 | Kubernetes namespace，默认 `default`。 |
| `labels` | 否 | 传播到 Kubernetes 资源的公共字符串 labels。 |

## spec.mode

| 值 | 必需 workload | 暴露方式 |
|---|---|---|
| `embedding` | 仅 `spec.embedding` | `direct` 或 `gateway` |
| `reranker` | 仅 `spec.reranker` | `direct` 或 `gateway` |
| `combined` | `spec.embedding` 与 `spec.reranker` | 必须为 `gateway` |

## 模型 workload

`embedding` 和 `reranker` 使用相同结构：

```yaml
embedding:
  model: jina-embeddings-v5-text-small
  runtime: gpu-opt
  replicas: 2
  image:
    repository: ghcr.io/jina-ai/jina-on-prem/jina-embeddings-v5-text-small
    digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  resources:
    cpu: "4"
    memory: 8Gi
    gpu: 1
  env:
    JINA_BATCH_TOKENS: "8192"
```

| 字段 | 默认值 | 说明 |
|---|---|---|
| `model` | 无 | 必须存在于 vendored catalog，并与所在 role 匹配。 |
| `runtime` | `cpu` | `cpu`、`gpu` 或 `gpu-opt`；reranker 不支持 `gpu-opt`。 |
| `replicas` | `1` | 1 到 100。 |
| `image.repository` | catalog repository | 不包含 tag 或 digest 的仓库地址。 |
| `image.digest` | 无 | `sha256:` 加 64 位小写十六进制。 |
| `resources.cpu` | catalog 默认值 | 正数字符串。 |
| `resources.memory` | catalog 默认值 | `Mi`、`Gi` 或 `Ti`。 |
| `resources.gpu` | CPU 为 0，GPU 为 1 | CPU runtime 禁止请求 GPU，GPU runtime 至少为 1。 |
| `env` | `{}` | 非敏感字符串环境变量。 |
| `secretEnv` | `[]` | 外部 Compose 环境变量和 Kubernetes Secret 引用。 |

疑似 `TOKEN`、`PASSWORD`、`API_KEY`、`LICENSE_KEY`、`SECRET` 或 credentials 的变量不能放入 `env`。

## 外部密钥引用

项目不创建 Secret，也不接受密钥明文：

```yaml
secretEnv:
  - name: JINA_LICENSE_KEY
    composeEnvironment: JINA_LICENSE_KEY
    kubernetesSecret:
      name: jina-license
      key: license-key
```

- Compose 输出 `${JINA_LICENSE_KEY:?set JINA_LICENSE_KEY}`，部署时从宿主环境读取。
- Helm/Kustomize 输出 `secretKeyRef`，Secret 必须由运维或外部 Secret 管理器预先创建。

完整示例见 `examples/embedding-secret.yaml`。

## exposure

```yaml
exposure:
  mode: gateway
  port: 8080
  gatewayImage: docker.io/nginxinc/nginx-unprivileged@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
```

| 字段 | 默认值 | 说明 |
|---|---|---|
| `mode` | `gateway` | `direct` 或 `gateway`。 |
| `port` | `8080` | Compose 主机端口或 Kubernetes Service port。 |
| `gatewayImage` | 固定版本 tag | combined gateway 镜像；生产 digest 模式下必须改为 digest。 |

## production

```yaml
production:
  requireImageDigest: true
  networkPolicy: true
  readOnlyRootFilesystem: true
```

- `requireImageDigest` 同时约束模型和 gateway。
- `networkPolicy` 控制 Helm/Kustomize 是否生成入口 NetworkPolicy。
- `readOnlyRootFilesystem` 控制模型容器根文件系统；gateway 始终为只读。
