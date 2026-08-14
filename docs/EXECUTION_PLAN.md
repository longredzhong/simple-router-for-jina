# simple-router-for-jina 重新开发执行计划

## 1. 目标

将项目重新实现为一个确定性的部署编译器。用户维护一份简单、版本化的 YAML 文件，CLI 将其校验并转换为统一部署模型，然后生成：

- embedding 服务；
- reranker 服务；
- embedding + reranker 组合服务；
- Docker Compose、Helm 或 Kustomize 部署产物。

项目不负责训练模型，也不重新实现 Jina 推理引擎。模型推理由受支持的 OCI 镜像承担。

## 2. 核心设计决策

### 2.1 单一配置入口

第一版只接受 YAML。配置使用 Kubernetes 风格的 `apiVersion`、`kind`、`metadata`、`spec`，便于演进和生成 JSON Schema。

旧 TOML 不作为长期输入格式；如需要兼容，提供一次性迁移命令，而不是维护第二套运行时解析链路。

### 2.2 统一 IR

所有 renderer 只能接受同一份规范化 IR：

```text
source YAML
  -> strict schema
  -> catalog capability resolution
  -> normalized immutable IR
  -> compose | helm | kustomize
```

IR 负责统一表达模型角色、镜像引用、运行时、端口、副本、CPU、内存、GPU、环境变量、探针、安全上下文和暴露方式。

### 2.3 组合服务拓扑

`combined` 由两个独立 workload 组成：

- embedding workload；
- reranker workload。

统一入口按 API path 转发请求。两个 workload 可以独立扩缩容和升级，避免模型内存、GPU 调度及故障域互相耦合。

### 2.4 渲染和部署分离

CLI 第一阶段只提供 `init`、`validate`、`catalog` 和 `render`。它不会默认运行 `docker compose up`、`helm upgrade` 或 `kubectl apply`。

这样生成结果可以进入 GitOps、代码审查、签名和变更审批流程。

### 2.5 确定性与离线

- 模型目录使用带来源信息的仓库内快照。
- renderer 不在运行时访问网络。
- 相同输入和项目版本必须生成字节一致的结果。
- 所有路径相对于输出目录闭合，禁止依赖调用时的当前目录。

## 3. 初始配置示例

```yaml
apiVersion: serving.jina.ai/v1alpha1
kind: JinaServing
metadata:
  name: search-models
  namespace: ai-serving
spec:
  mode: combined
  embedding:
    model: jina-embeddings-v5-text-small
    runtime: gpu-opt
    replicas: 2
    resources:
      cpu: "4"
      memory: 8Gi
      gpu: 1
  reranker:
    model: jina-reranker-v3
    runtime: gpu
    replicas: 1
    resources:
      cpu: "4"
      memory: 8Gi
      gpu: 1
  exposure:
    mode: gateway
    port: 8080
  production:
    requireImageDigest: false
    networkPolicy: true
```

开发示例允许 catalog 中的可变标签。生产环境应设置 `requireImageDigest: true` 并为每个模型提供 digest。

## 4. 计划与交付物

### 阶段 0：清理旧实现

状态：已完成。

交付：

- 删除单文件 Router、旧 Dockerfile、旧 Compose 生成逻辑、旧示例和旧发布配置。
- 保留许可证和版本历史，保证可回滚。

验收：工作区不再包含旧运行代码或旧用户文档。

### 阶段 1：项目骨架、配置和 IR

状态：已完成。

交付：

- `pyproject.toml` 和标准 `src/` 包结构。
- 严格的配置 Schema 与清晰错误信息。
- 带来源 metadata 的最小模型 catalog 快照。
- 配置到不可变 IR 的 compiler。
- `init`、`validate`、`catalog list/show` CLI。
- JSON Schema 导出。

验收：

- embedding、reranker、combined 示例均能通过校验。
- 错误角色、非法 runtime、重复名称、错误资源和未知字段被拒绝。
- `gpu-opt` 不能用于 reranker。
- 单元测试、ruff 和格式检查通过。

### 阶段 2：Docker Compose renderer

状态：已完成。

交付：

- `render compose`。
- embedding、reranker、combined 三种输出。
- 健康检查、资源限制、GPU reservation、非 root、只读文件系统和 `/tmp` tmpfs。
- combined 的统一入口配置。

验收：

- 渲染快照测试通过。
- 输出目录可以整体移动，不包含源配置绝对路径。
- `docker compose config` 通过；若本机 Docker Compose 不可用，明确记录为未验证。

### 阶段 3：Helm renderer 与 Chart

状态：进行中。

交付：

- 可独立发布的 `charts/jina-serving`。
- CLI 从 IR 生成确定性的 `values.generated.yaml`。
- Deployment、Service、ConfigMap、Ingress、NetworkPolicy、PDB 和可选 ServiceAccount。
- startup、readiness、liveness probes 与完整 pod/container security context。

验收：

- 三种 mode 的 `helm lint` 与 `helm template` 通过。
- selector、Service port、探针、GPU limits 和安全上下文由自动化测试断言。
- production 模式拒绝未固定镜像。

### 阶段 4：Kustomize renderer

状态：待开始。

交付：

- 由相同 IR 生成的 base resources。
- `dev`、`prod` overlay 示例。
- image、replicas、namespace 和常用资源覆盖入口。

验收：

- `kustomize build` 或 `kubectl kustomize` 通过。
- 构建结果通过 Kubernetes Schema 校验。
- 与 Helm 的核心 workload 契约通过结构化测试保持一致。

### 阶段 5：CI、文档与运行验证

状态：待开始。

交付：

- CI 中的 lint、typecheck、test、build 和三种 renderer 验证。
- 中文 README、配置参考、部署指南、升级指南和安全说明。
- CPU 真实镜像 smoke 脚本。
- 独立 GPU 与 Kubernetes 验收清单。

验收：

- wheel/sdist 能安装并运行 CLI。
- 所有文档示例通过 Schema 和 renderer 验证。
- CPU smoke、GPU smoke、Kubernetes smoke 分别报告，不相互替代。

## 5. 非目标

第一版不实现：

- 模型训练、量化或权重下载器；
- 任意多模型动态 body 路由；
- 自动创建云 GPU 集群；
- 自动写入 Kubernetes Secret；
- 默认执行生产部署；
- 以 CPU/内存 HPA 冒充 GPU 推理吞吐扩缩容策略。

## 6. 提交策略

每个阶段独立提交。阶段内部如必须拆分，按“Schema/IR → renderer → 验证/文档”的可运行边界提交。每个 commit 必须满足：

1. 主题单一；
2. 对应测试通过；
3. `git diff --check` 通过；
4. 不包含用户无关文件；
5. 在提交消息中体现行为变化。

本计划只授权本地 commit，不授权 push 或真实部署。
