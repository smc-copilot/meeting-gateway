# 来源、版本与可复核边界

日期：2026-10-16。版本：1.0.0rc1。

## 设计来源

本包根据本次对话确认的 `docs/design.md` 实现。用户确认的架构为独立 Meeting 服务、Backend 身份来源、Meeting 权限执行、REST/MCP 共享服务、企业自建与 OAuth 双通道。`docs/tencent-setup.md` 是相应配置检查清单。

## 仓库接口依据

核对仓库：`https://github.com/loudon84/nodeskclaw`。
核对提交：`83edfb0d97f07920deb8bb9ce44a91e3e32cc3af`。

实际读取的关键文件：

| 路径 | 实现所依赖的约定 |
|---|---|
| `lat.md/architecture/knowledge.md` | 独立服务、自有数据库、Backend 身份上下文、外部系统适配层 |
| `lat.md/architecture/task.md` | Python 子项目布局、uv、Alembic、作业表、软删除与错误契约 |
| `nodeskclaw-task/pyproject.toml` | Python 3.12、FastAPI、SQLAlchemy asyncio、测试工具和包发现 |
| `nodeskclaw-backend/app/api/auth.py` | `get_current_user`、成员上下文和 `ApiResponse` 结构 |
| `nodeskclaw-backend/app/models/{user,organization,org_membership}.py` | 组织、成员、用户、软删除、启用状态与强制改密字段 |
| `nodeskclaw-backend/app/services/org/{factory,single_org}.py` | `get_org_provider().resolve_org_for_user(user, db)` 返回组织对象 |
| `nodeskclaw-backend/app/api/router.py` | `api_router` 聚合注册点 |
| `nodeskclaw-portal/src/router/index.ts` | Vue Router `ceRoutes` 扩展点 |
| `nodeskclaw-portal/src/stores/auth.ts` | `useAuthStore().token` 的既有登录身份来源 |
| `LICENSE` | Apache-2.0 上游许可文本 |

Backend addon 是新增 Meeting 身份接口，不把 Knowledge 上下文当成会议权限。安装器对原文件做有限、可回滚的变更。接口核对不等于已部署整个仓库的集成回归；仍需在你们的目标分支实际安装、构建和测试。

## 腾讯与协议依据

以下地址是实现时检查的官方契约。接口权限、套餐、授权开放范围和字段可能由腾讯更新，生产接入必须用自己的两类应用验证。源码不会通过自动跨通道替换身份来补偿不支持的接口。

| 能力 | 官方依据 |
|---|---|
| REST 签名 | `https://cloud.tencent.com/document/product/1095/42413` |
| 创建会议 | `https://cloud.tencent.com/document/product/1095/42417` |
| 企业录制列表 | `https://cloud.tencent.com/document/product/1095/53224` |
| 会议录制列表 | `https://cloud.tencent.com/document/product/1095/51189` |
| 单个录制详情 / 地址 | `https://cloud.tencent.com/document/product/1095/51180` |
| 录制转写详情 | `https://cloud.tencent.com/document/product/1095/65111` |
| 智能纪要 | `https://cloud.tencent.cn/document/product/1095/109458` |
| OAuth 接入 / 令牌与用户资料 | `https://cloud.tencent.com/document/api/1095/51257` |
| STS 生成 | `https://cloud.tencent.com/document/product/1095/127650` |
| STS 回调 | `https://cloud.tencent.com/document/product/1095/127651` |
| Webhook 验签、解密与确认 | `https://cloud.tencent.com/document/api/1095/51608` |
| 官方调试工具 | `https://cloud.tencent.com/document/product/1095/51815` |
| MCP Streamable HTTP | `https://modelcontextprotocol.io/specification/2025-11-25/basic/transports` |
| MCP HTTP 授权 | `https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization` |

MCP 明确固定在 design 选择的 `2025-11-25` 协议，不宣称支持后来所有版本。首版实现无状态 JSON 响应模式；不提供可选的服务器主动 SSE 推送。SDK 合同测试约束在 `mcp>=1.23,<2`，实际 SDK 客户端会话仍是外部验收门槛。

## 依赖与环境

本次使用实际已安装的依赖执行本地测试；精确顶层版本在 `pyproject.toml`。未能联网解析全量依赖图，因此本包不声称提供可复现的传递依赖锁，也没有编造 `uv.lock` 或 wheel 哈希。正式部署前运行联网锁定脚本、审核依赖与镜像版本。

没有运行任何真实腾讯创建、取消、下载或 OAuth 授权，没有使用用户真实密钥。测试身份及上游响应仅存在于 `tests/`；生产 Runtime 没有模拟成功或测试管理员的默认分支。所有源码以候选版本提供，需要正常代码评审和现场联调。
