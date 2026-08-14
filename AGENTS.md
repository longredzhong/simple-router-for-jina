# AGENTS.md

本文件是仓库开发与自动化 Agent 的最高优先级项目约定。除非用户明确覆盖，所有修改都必须遵守这些边界。

## 产品目标

本项目提供一个 Python CLI，通过单一、版本化的 YAML 配置生成可部署的 Jina embedding、reranker 或 embedding + reranker 服务。

必须支持以下输出目标：

- Docker Compose：本地开发、验证和单机部署。
- Helm：主要 Kubernetes 生产部署目标。
- Kustomize：提供可审查的 base 与环境 overlay 入口。

`combined` 表示统一访问入口下的两个独立 workload。embedding 与 reranker 必须能够独立设置镜像、资源、副本和生命周期，不能默认运行在同一容器或 Pod 中。

## 架构边界

配置处理链路固定为：

```text
YAML -> schema validation -> normalized deployment IR -> target renderer
```

- `config` 负责输入模型、解析、错误定位和版本迁移。
- `catalog` 负责模型类型、运行时能力、默认镜像与来源版本。
- `compiler` 只生成与部署目标无关的不可变 IR。
- `renderers` 只能消费 IR，不得重新解释原始 YAML。
- `gateway` 是可选组件，仅负责 combined 或多模型统一入口，不能承担模型推理。
- CLI 的 `render` 与外部系统的 `apply/deploy` 必须分离；默认命令不得修改 Docker 或 Kubernetes 状态。

## 配置契约

- 第一版规范输入只支持 YAML。
- 顶层必须包含 `apiVersion`、`kind`、`metadata` 和 `spec`。
- API 初始版本为 `serving.jina.ai/v1alpha1`，kind 为 `JinaServing`。
- `spec.mode` 只能为 `embedding`、`reranker` 或 `combined`。
- 生产模式必须支持要求镜像 digest；不得静默使用 `latest`。
- `gpu-opt` 只能用于 catalog 明确标记支持该能力的 embedding 模型。
- 密钥只能使用环境变量名、Secret 引用或外部网关引用，不能写入生成清单。
- 未知字段默认拒绝，避免拼写错误被静默忽略。

## 生产安全基线

生成的生产资源默认满足：

- 非 root 用户。
- 只读根文件系统，并为 `/tmp` 提供临时可写空间。
- 禁止提权，丢弃 Linux capabilities，启用 RuntimeDefault seccomp。
- Kubernetes 使用 startup、readiness 和 liveness 探针。
- 模型镜像可按 OCI digest 固定。
- 不内置明文认证密钥或 TLS 私钥。
- Kubernetes 默认生成最小入口 NetworkPolicy；出口策略必须由配置显式选择。
- GPU 数量必须显式映射为 Compose device reservation 或 `nvidia.com/gpu` limit。

Jina 模型容器本身没有认证和 TLS。公网暴露必须通过外部 Ingress、Gateway 或反向代理完成身份验证与 TLS 终止。

## 开发顺序

权威执行计划位于 `docs/EXECUTION_PLAN.md`。实现顺序不得随意打乱：

1. 配置 Schema、catalog、IR 与 CLI。
2. Docker Compose renderer。
3. Helm Chart 与 values renderer。
4. Kustomize base/overlay renderer。
5. CI、操作文档和分层 smoke test。

如后续步骤暴露出 IR 缺陷，应先在独立提交中修正 IR 与测试，再继续 renderer，禁止只在某一个 renderer 内打补丁。

## 提交纪律

- 每个执行计划步骤必须是独立 commit。
- commit 前必须运行该步骤声明的最小验证。
- commit 只包含当前主题；保留无关的用户改动和未跟踪文件。
- 不得 amend、rebase、force push 或自动 push，除非用户明确要求。
- 生成物、缓存、虚拟环境和本地密钥不得提交。
- 破坏兼容性的配置变更必须更新 `apiVersion`、迁移说明或两者。

建议提交前缀：`feat:`、`fix:`、`docs:`、`test:`、`chore:`、`refactor:`。

## 验证要求

所有 Python 修改至少运行：

```bash
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

目标特定验证：

- Compose：`docker compose -f <rendered-file> config`。
- Helm：`helm lint` 与 `helm template`。
- Kustomize：`kubectl kustomize` 或 `kustomize build`。
- Kubernetes YAML：有可用工具时运行 `kubeconform`。

外部工具不可用时，必须保留确定性的单元/快照测试，并明确记录未验证项；工具缺失不能报告为通过。

真实模型验证分层记录：

- 静态配置与渲染测试。
- CPU 镜像启动和 API smoke。
- GPU 镜像启动和 API smoke。
- 真实 Kubernetes 部署。

前一层通过不能代替后一层。

## 文档要求

- 文档正文使用中文。
- 命令、路径、配置键、API 名称和代码标识保持原文，确保可复制。
- 示例必须能通过当前 Schema 验证。
- 所有生产声明必须关联自动化验证或明确标注“未验证”。
- README 只描述已经实现的功能；规划内容放在执行计划中。

## 依赖与上游数据

- 运行时依赖保持最小化；构建、测试和发布依赖必须放在开发依赖组。
- 模型 catalog 使用仓库内快照保证离线与确定性，必须记录上游 URL、revision 和同步时间。
- 更新 catalog 必须通过专用脚本完成，并提交来源变化与验证结果。
- 渲染结果必须确定性排序，不得依赖当前工作目录、哈希随机性或网络状态。
