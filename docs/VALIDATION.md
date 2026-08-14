# 验证状态

本文件区分确定性验证与需要外部基础设施的运行验证。前一层通过不能证明后一层。

## 当前已验证

在 2026-08-14 的本地工作区完成：

- Ruff lint 与 format check；
- 36 个 pytest 测试；
- embedding、reranker、combined 三种模式的 `docker-compose config`；
- 三种模式的 `helm lint` 与 `helm template`；
- 三种模式的 Kustomize `base`、`overlays/dev`、`overlays/prod`，共 9 次 `kustomize build --enable-helm`；
- 外部密钥示例的 Compose 变量替换、Helm `secretKeyRef` 和 Kustomize `secretKeyRef`；
- sdist 与 wheel 构建；
- 在临时 Python 3.13 环境中从 wheel 安装 CLI；
- wheel 中包含 Chart、templates 和 `values.schema.json`；
- 从已安装 wheel 渲染的 Chart 通过 `helm lint`。

使用的主要本地工具：

- Python 3.13.7（构建 wheel 安装验证）；
- Ruff 0.16.2；
- Helm 4.2.3；
- Docker Compose 独立命令；
- Kustomize 独立命令。

## 尚未验证

- 真实 Jina CPU 模型镜像启动和推理响应；
- NVIDIA GPU runtime、GPU 模型加载、显存和吞吐；
- `gpu-opt` 并发 batching 行为；
- 真实 Kubernetes 集群调度、探针、NetworkPolicy 和滚动升级；
- Ingress、TLS 和身份验证集成；
- `kubeconform` 或等价 Kubernetes OpenAPI Schema 验证；
- GitHub Actions workflow 的远端运行结果；
- 生产 registry、OCI 签名、SBOM 和 admission policy。

## 运行验证入口

已准备本地镜像后执行：

```bash
scripts/smoke-image.sh embedding \
  ghcr.io/jina-ai/jina-on-prem/jina-embeddings-v5-text-small@sha256:...

scripts/smoke-image.sh reranker \
  ghcr.io/jina-ai/jina-on-prem/jina-reranker-v3@sha256:...
```

脚本默认拒绝隐式拉取镜像。GPU 验收需要显式第三个参数：

```bash
scripts/smoke-image.sh embedding IMAGE_REFERENCE gpu
```

每次运行必须记录镜像 digest、硬件、Docker/NVIDIA runtime 版本、请求、响应摘要和退出状态。
