# simple-router-for-jina

`simple-router-for-jina` 是一个 Jina 推理服务部署编译器。它读取一份版本化 YAML，完成严格校验和模型能力解析，然后生成 Docker Compose、Helm 或 Kustomize 部署包。

当前支持：

- 单 embedding 服务；
- 单 reranker 服务；
- 独立 embedding 与 reranker workload 组成的 combined 服务；
- CPU、GPU，以及 catalog 明确支持的 embedding `gpu-opt` runtime；
- 模型和 gateway OCI digest 固定；
- Compose 外部环境变量与 Kubernetes `secretKeyRef` 形式的密钥引用。

项目不下载或训练模型，也不会默认执行部署。Jina 推理由 `jina-on-prem` OCI 镜像承担。

## 安装开发环境

需要 Python 3.11 或更高版本以及 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync --extra dev
uv run jina-serving --help
```

兼容命令 `simple-router` 指向同一个新 CLI，但旧版 TOML 和旧命令参数已移除。

## 快速开始

创建并校验 combined 配置：

```bash
uv run jina-serving init --mode combined --name search-models --output serving.yaml
uv run jina-serving validate --config serving.yaml
```

也可以直接使用仓库示例：

```bash
uv run jina-serving validate --config examples/embedding.yaml
uv run jina-serving validate --config examples/reranker.yaml
uv run jina-serving validate --config examples/combined.yaml
```

查看离线 catalog 和配置 JSON Schema：

```bash
uv run jina-serving catalog list
uv run jina-serving catalog show jina-embeddings-v5-text-small
uv run jina-serving schema --output schema.json
```

## 生成部署包

```bash
uv run jina-serving render compose \
  --config examples/combined.yaml \
  --output build/compose

uv run jina-serving render helm \
  --config examples/combined.yaml \
  --output build/helm

uv run jina-serving render kustomize \
  --config examples/combined.yaml \
  --output build/kustomize
```

输出目录是自包含和可移动的，不挂载源配置文件，也不依赖仓库相对路径。重复写入已有 renderer 文件必须显式指定 `--force`。

## 生产边界

- `production.requireImageDigest: true` 会要求所有模型镜像以及 combined gateway 镜像使用 OCI digest。
- upstream 模型服务本身没有认证和 TLS；生产环境必须通过外部 Ingress、Gateway 或反向代理添加身份验证和 TLS。
- combined 模式不会把两个模型装进同一 Pod；它们拥有独立的镜像、副本、资源、探针和 Service。
- Compose 适合本地、验证和单机部署；Kubernetes 生产部署优先使用 Helm 或 Kustomize。
- 当前内置 catalog 是带上游 revision 的 8 模型离线快照，不等同于上游完整模型集合。

详细说明：

- [执行计划](docs/EXECUTION_PLAN.md)
- [配置参考](docs/CONFIGURATION.md)
- [部署指南](docs/DEPLOYMENT.md)
- [安全边界](docs/SECURITY.md)
- [验证状态](docs/VALIDATION.md)

## 验证

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
scripts/validate-renderers.sh
uv build
```

Renderer 验证覆盖 `docker compose config`、`helm lint/template` 和 `kustomize build --enable-helm`。真实 CPU 模型启动、GPU 推理和真实 Kubernetes 集群部署属于独立验收层，尚不能由静态渲染结果替代。

## License

MIT。模型权重和上游 OCI 镜像有各自许可证，部署前必须根据 catalog 上游来源单独核对。
