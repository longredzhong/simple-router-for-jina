# 安全边界

## 上游服务边界

Jina on-prem 模型容器监听 plain HTTP 8080，本身没有请求身份验证或 TLS。生成器不会虚构这些能力。

生产入口必须由组织已有的 Ingress、Gateway、service mesh 或反向代理承担：

- TLS 终止和证书轮换；
- API key、JWT、mTLS 或其他身份验证；
- 限流、审计和访问日志；
- 面向公网的 WAF 或边界策略。

## 容器安全基线

Compose、Helm 和 Kustomize 输出默认包括：

- 模型容器 UID/GID 65534；
- gateway UID/GID 101；
- `readOnlyRootFilesystem` 或 Compose `read_only`；
- `/tmp` 等必要路径使用临时卷；
- `allowPrivilegeEscalation: false`；
- Linux capabilities 全部丢弃；
- `RuntimeDefault` seccomp；
- startup、readiness 和 liveness probes；
- 有限日志轮转或资源 requests/limits。

GPU 访问通过 Compose NVIDIA device reservation 或 Kubernetes `nvidia.com/gpu` limit 授予，不需要 root。

## 密钥

密钥不得出现在 YAML、生成文件或 Git 历史中。

- Compose 只引用部署主机已有环境变量，并在缺失时停止解析。
- Kubernetes 只引用已有 Secret key。
- 项目不创建 Secret；建议结合 External Secrets、Sealed Secrets、SOPS 或平台 Secret 管理器。
- 普通 `env` 会拒绝常见 secret-like 变量名称，但这不是完整的数据泄漏检测，代码审查仍然必需。

## NetworkPolicy

默认策略限制模型 workload 的入口：

- combined 模式仅允许同一 release 的 gateway Pod 访问模型端口；
- direct 模式仅允许同 namespace Pod 访问；
- gateway 默认允许同 namespace Pod 访问。

当前策略不限制 egress。多模态模型可能根据请求中的 HTTP(S) URL 拉取媒体，完全离线环境应另外配置 egress deny 和必要的 DNS 例外。

Ingress controller 位于其他 namespace 时，需要在部署环境中为 gateway NetworkPolicy 增加明确来源；不要简单删除所有网络策略。

## 镜像与供应链

- 生产模式使用 OCI digest，而不是 `latest` 或可变 runtime tag。
- catalog 记录上游 URL、commit revision 和同步日期，运行时不会联网更新。
- 到达内部 registry 后仍应执行组织现有的漏洞扫描、SBOM、签名与准入策略。
- 模型权重许可证独立于本项目 MIT 许可证，部署负责人必须核对商业使用条件。

## 尚未覆盖

当前实现不提供：

- 内置认证服务器；
- TLS 证书创建和轮换；
- Kubernetes Secret 创建；
- egress allowlist；
- 运行时审计存储；
- 镜像签名验证 admission policy。

这些能力应由平台边界提供，而不是向模型容器重复塞入一套不完整的安全系统。
