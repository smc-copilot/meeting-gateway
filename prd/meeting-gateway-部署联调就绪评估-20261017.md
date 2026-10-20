---
title: meeting-gateway 指定白名单服务器部署与腾讯会议联调就绪评估
review_date: 2026-10-17
repository: smc-copilot/meeting-gateway
branch: master
commit: e966bd90637fd2ae95635635596779be99cf29b8
review_type: SOURCE_AND_EXISTING_CI_REVIEW
production_release_status: NOT_VERIFIED
source_mutation: NONE
---

# meeting-gateway 部署联调就绪评估

## 1. 结论与边界

**建议有条件部署到腾讯会议白名单服务器，先开展受控的应用授权、AK/SK 签名、Webhook、STS 和指定资源只读联调；不能据此认定双通道业务接口和整体发布门禁已经全部通过。**

当前代码不是空脚手架。数据库迁移、API、Worker、应用配置、OAuth、AK/SK、STS、权限和内容读取都有实现；但业务查询/创建仍存在明确的 OAuth-only 限制，在线测试文件和 smoke 脚本仍有占位行为，Portal 的实际 CI 构建失败。

“能部署做调试”不等于“正式发布通过”。本报告允许的是受控测试环境部署建议，不是生产上线批准。

### 1.1 本轮实际做过的检查

- 通过 GitHub 连接器读取 master 的固定 SHA、部署文件、关键服务、业务路由及测试。
- 读取同 SHA 的 GitHub Actions 执行结果和两个 job 的日志。
- 对当前 `scripts/tencent_live_smoke.py` 进行隔离本地执行，执行前校验 Git blob SHA-1 与仓库相同。
- 核对腾讯官方的来源 IP 白名单、OAuth 回调和 STS 文档。

### 1.2 本轮没有做的事项

没有修改远端或本地产品源码，没有推送提交，没有在指定服务器启动 Docker，没有使用真实凭证调用腾讯 API，没有重新在本环境执行当前仓库完整测试。完整测试数字来自同 SHA 的 CI 日志，不是旧 RC1 报告，也不是本机全量复测。

目标服务器的实际出口 IP、操作系统、证书、Backend 地址及凭据本轮未取得，故这些只能列为现场验证条件，不能声称已通过。

## 2. 固定代码基线与 CI 证据

| 项目 | 核查结果 |
|---|---|
| 分支 | master |
| Commit | e966bd90637fd2ae95635635596779be99cf29b8 |
| GitHub Actions run | 38985761134，Meeting gateway gates |
| CI 总状态 | FAILURE |
| Python job | 117256737050：安装/迁移/测试/编译步骤成功，Ruff 步骤失败 |
| Portal job | 117256736871：集成安装成功，完整构建失败 |
| 测试摘要 | 154 collected；148 passed；6 skipped；0 failed |
| 语句覆盖率 | 77%，并非功能完成比例 |
| 测试环境 | Python 3.12.15；CI 配置 PostgreSQL 16 |
| 迁移 | initial revision 与 add_client_create_policy 均执行 |
| 完整镜像启动 | 该 CI 没有 Docker 镜像构建、Compose 全栈启动步骤 |

注意：`tests/contracts/test_external_gates.py` 的 PostgreSQL 用例验证的是独立连接 advisory lock 和单作业竞争领取。不能扩写成“所有业务在生产 PostgreSQL 多进程下均验证通过”。

新的 `tests/integration/test_mcp_sdk_session.py` 在该 CI 中通过，比旧包的 SDK 类型校验前进一步；也不等于真实智能体客户端、真实身份系统与腾讯资源已端到端验证。

## 3. 现在可以复用的实现

| 能力 | 当前源码依据 | 判断 |
|---|---|---|
| 独立部署 | Dockerfile、deploy/compose.yaml、app/main.py、app/worker.py | 有 API、Worker、PostgreSQL、一次性迁移服务 |
| 生产配置校验 | app/core/config.py、app/cli.py | 校验 HTTPS、密钥及 PostgreSQL 等；可生成私有 .env |
| 企业应用 | app/services/connection_service.py、TencentClient | AK/SK 连接、身份绑定和固定接口调用已存在 |
| OAuth | ConnectionService.oauth_start/oauth_callback/oauth_credentials | 有 state、回跳、加密凭证、刷新和状态处理 |
| STS | request_sts/maintain_sts/receive_sts/_associate | 有 req_id 关联、早到回调、更新和过期处理 |
| 诊断 | DiagnosticService.PROBES | 已有 configuration、oauth_user_info、upcoming、history、records、corp_records、record_detail、transcript、minutes |
| 分页转写 | ContentService.fetch | 增加 checkpoint、恢复及完整性发布逻辑；不是旧版只从第一页重试 |
| 创建策略 | OperationService.prepare/confirm_business | TRUSTED_MEMBER 可直接排队；HUMAN_CONFIRM 可从内部业务接口确认 |
| 源查询 | POST /api/v1/meeting-queries | 接口存在，但实现范围有限，见下文 |
| 内容、下载 | business.py、content_service.py 等 | 已有实际服务逻辑；媒体域名、权限和真实文件仍须现场验证 |
| 事件 | EventService.receive/process_inbox/publish/deliver | 收件箱、已知文件处理、发件箱及投递逻辑存在 |

**无需重新做员工账号、会议工作台或腾讯接口基础 SDK。主要工作是补业务路径、补真实测试工具并完成部署绑定。**

## 4. 部署文件检查

### 4.1 Compose 的交付边界

`deploy/compose.yaml` 包含 `postgres / migrate / api / worker`，其中 API 映射为 `127.0.0.1:4522:8000`，API 与 Worker 共用私有数据卷，镜像平台为 linux/amd64。

该文件不包含 Backend、Portal 或 Nginx。它们可以位于其他部署中，不需要都迁到白名单服务器，但必须建立真实网络连通和身份服务合同。不能把默认地址 `http://nodeskclaw-backend:8000` 当作在独立 Compose 网络中天然可解析的地址。

### 4.2 锁文件已经存在，但 Docker 构建没有采用

当前仓库包含 `uv.lock`；README 仍保留“没有生成 uv.lock”的旧说明。Dockerfile 只复制 pyproject.toml、app、alembic 等，使用 `pip install .`，不复制或冻结使用 uv.lock。

影响：不代表镜像必然无法启动，但在依赖有范围约束时，目标服务器镜像的依赖集合可能不同于 CI。建议将镜像安装改为使用现有锁文件的冻结安装，或由锁文件生成带校验的依赖安装输入，并新增镜像启动测试。不要因为旧 README 写“无锁文件”而重复从零设计依赖方案。

### 4.3 健康检查不能作为授权就绪证明

`/health/live` 仅证明进程存活。`/health/ready` 返回 `database` 和 `backend` 布尔值，但 HTTP 状态仅由数据库结果决定；Backend 不可用时仍可返回 HTTP 200。这是保留回调接收能力的设计，不宜为了一个部署检测直接改坏回调可用性。

部署验收应解析响应体并实际执行成员 context/resolve；不要只使用 `curl -f /health/ready` 判定腾讯业务已经可调。

### 4.4 Nginx 需要现场替换的配置

`deploy/nginx.conf.example` 包含占位域名、证书路径，以及默认仅允许 `10.0.0.0/8` 和 `127.0.0.1` 的内部 API 访问规则。回调、OAuth 与授权元数据路径分别转发。

现场应填写实际域名、证书、内部应用/管理员的真实来源网段；不能直接开放全部 API，也不能把 Nginx 的 403 误认为腾讯授权失败。生产配置默认关闭 OpenAPI 在线文档；接口调试使用仓库的合同文件和受控工具，不应为方便调试公开整个管理面。

## 5. 明确的代码缺口与阻断范围

以下按“阻断什么”分级，不把所有问题都归成启动故障。

### F-01 — 源查询与创建的业务层仍然只接受 OAuth 连接

**证据：**
- `QueryService.submit()`、`run()` 要求主体为 MEMBER，并要求连接为 `THIRD_PARTY_OAUTH` 且属于该员工；`CORP_WINDOW` 直接返回 PERMISSION_DENIED。
- `OperationService._parameters()` 拒绝 SERVICE、拒绝 host_member_id 不同于当前员工、拒绝非 OAuth 连接；APPROVED_SERVICE 同样被拒绝。
- `tests/acceptance/test_phase1_gateway.py` 明确测试拒绝 CORP_WINDOW、APPROVED_SERVICE 和代建，说明其中一部分是当前 phase-1 的主动范围限制。

**判断：**
这些限制不是到白名单服务器上就会消失的腾讯限制，而是请求尚未到腾讯前的本地代码判断。不能将“底层已经有 AK/SK adapter”宣称为“企业自建应用对内创建和源查询也完整可用”。

**阻断范围：**不阻断企业应用配置、签名诊断、STS 或已授权采集；阻断通过当前业务源查询/创建入口实现企业应用主通道。系统无人值守创建和授权代建也尚未开放。

**建议修改：**在保持员工/组织/资源授权的前提下，为企业连接增加独立的用户查询与本人创建路径；企业范围查询单独采用明确的系统/管理员授权。不能删除权限判断并借用全能管理员作为修复。

**验收：**同一内部调用方，允许的 OAuth 与 AK/SK 连接各能查询已知会议；AK/SK 本人创建能到达上游并取得可核对结果；不允许的主体仍为 403，拒绝路径零腾讯业务写入。

### F-02 — USER_WINDOW 源查询只请求第一页

**证据：**`QueryService.run()` 的 USER_WINDOW 固定调用 history，`page=1`、`page_size=20`，随后写入返回会议并 return；没有下一页循环、总页处理或续传状态。

**影响：**查询时间范围包含超过 20 场会议时，代码不会主动取得后续页。不能把作业完成当作整个时间窗已完整查询。大于腾讯接口允许的时间窗口也需要切片或明确拒绝，当前该分支未见切片逻辑。

**阻断范围：**不阻断第一场授权验证；阻断完整历史范围查询验收。

**验收：**准备至少 41 场测试会议的合成分页响应，最终取齐并去重；页间限流不重新从第一页开始；返回可机器判断的完整性/分页结果，而不是静默完成。

### F-03 — ensure 查询的连接支持与资源类型不一致

**证据：**
- `ensure_meeting()` 可为已有企业连接的会议排入 SOURCE_QUERY，但 `QueryService.run()` 又拒绝企业连接。
- `GET /meetings/{id}/recordings?fetch=ensure` 调用的是会议详情 ensure，再读取本地录制列表；没有为该请求直接安排目标会议录制刷新。
- SOURCE_QUERY 仅 upsert Meeting，不写 Recording。

**影响：**企业会议详情过了新鲜度阈值后，默认 ensure 可能返回 202，后台作业随后因连接类型被拒绝；首次只导入会议元数据后查录制，可能得到尚未采集的本地空列表。

系统另有个人定时同步和事件补偿：`MaintenanceService.personal_sync`、`EventService._schedule_personal` 需要相应客户端/权限，不能据此断言永远取不到录制，但它们也不等于本次 ensure 已保证目标资源刷新。

**阻断范围：**可用明确的 cache 读取或受控同步完成首轮诊断；默认业务查询闭环尚需补齐。

**验收：**过期企业会议详情 ensure 能成功完成或立即给出明确不支持，而不是排入必败作业；录制 ensure 应触发正确的录制获取，并区分“上游确实无录制”和“本地尚未获取”。

### F-04 — 在线测试脚本和用例仍是占位实现

**证据：**
- `scripts/tencent_live_smoke.py` 在 MEETING_LIVE=1 且配置齐全时，仅输出 `NOT_RUN / LIVE_CLIENT_NOT_BUNDLED`，随后退出码 0，没有发出 HTTP 请求。
- `tests/live/test_tencent_live.py` 的 3 个用例即使 MEETING_LIVE=1 仍会 pytest.skip。
- `tests/live/test_internal_consumer.py` 的 3 个用例也都会 skip；存在 golden-consumer 文件仍不能使其真正运行。

**本轮隔离复现：**当前脚本 Git blob SHA-1 已验证为 `998c477cb43dc5921fcf6a1961d98fcbdd0343d7`。使用假地址、假 Token，配置齐全仍返回 exit 0 和 NOT_RUN；详情见 `smoke_probe_results.json`。没有真实网络请求。

**阻断范围：**不阻断通过受控 HTTP 工具手工联调；阻断“部署到白名单 IP 后直接运行现有脚本自动验收”的承诺。

**建议修改：**实现实际调用网关的只读 smoke：连接诊断、特定会议/录制查询、STS 状态、转写和纪要读取；输出脱敏实际资源、状态及 trace。未执行或前置条件不满足时，在线验收模式返回非零；写入测试单独显式启用并限定测试人员与次数。

### F-05 — OAuth 对内启动已支持，但完成确认仍使用 Portal 管理面身份

**证据：**业务接口 `POST /api/v1/oauth/authorizations` 可启动授权并支持登记的 return_to。腾讯回调将连接置为 PENDING_CONFIRMATION；confirm_oauth 仍要求 admin.human，路由位于 `/api/v1/portal/connections/{connection_id}/confirm`，业务路由未提供相应连接确认入口。

**影响：**返回内部系统不意味着连接自动 ACTIVE。首次联调可让真实员工使用 Backend Bearer 调用现有确认路由，不必先做完整新 UI；但面向普通内部系统的一体化授权完成流程还不闭合。

**建议修改：**增加基于可信员工身份的对内确认接口，或者正式定义受控 Backend/BFF 代办合同；保留同一员工、同一组织、同一连接和单次授权的绑定。不能通过内部应用任意填写 member_id 代替员工确认，也不应把客户端密钥暴露给浏览器。

### F-06 — Portal 构建当前失败，但不必阻塞纯 API 首轮联调

CI 日志明确报告以下问题：

| 文件 | 错误 |
|---|---|
| `src/features/meeting/client.ts:7` | TS1294，constructor 参数属性与 erasableSyntaxOnly 不兼容 |
| `src/features/meeting/locale.ts:30,61` | TS1117，对象字面量重复属性 |
| `src/features/meeting/locale.ts:83` | TS2550，目标库不支持 replaceAll |
| `src/components/members/MemberModelTokenDialog.test.ts:47` | 基线 MemberInfo fixture 缺字段，不是 Meeting 新模块文件 |

应区分 Meeting 增量错误和被集成基线错误；不要把全部失败都归因于基线。无需为 API 调试重做 Portal，但若采用原页面配置/确认，至少修复对应构建问题并完成该基线构建。

Python Ruff 也失败；主要存在压缩写法、导入与风格问题。测试/编译已通过不等于 Ruff 已通过；反之不能仅凭这些 lint 报错认定服务肯定无法启动。整体发布门禁仍不是 PASS。

### F-07 — OAuth 上游临时故障仍有错误分类边界

**证据：**`TencentClient._raise_upstream` 在部分已知错误分支之后使用 `if oauth_channel or status==401`，导致 OAuth helper 返回未识别的 JSON HTTP 500 时，也会落入 UPSTREAM_REAUTH_REQUIRED。`ConnectionService._refresh_fault` 随后会将连接转成 REAUTH_REQUIRED。

另一个边界是业务 REST OAuth 请求仍以 `_send(..., write=...)` 调用，未单独传入连接鉴权类型；`oauth` 布尔值还同时控制 OAuth helper 的 `data` 包装解析，故不能简单将所有 OAuth 业务调用设置 oauth=True，否则会破坏普通 REST 响应解析。

**判断：**网络异常已增加 DEGRADED/恢复处理，不应再按旧版“一切异常都重新授权”描述；但 HTTP 错误与鉴权通道区分仍需补充。

**建议修改：**分离 `credential_channel` 和 `response_envelope`；HTTP 5xx/暂时错误保留授权并退避，明确凭据失效才重新授权。加入 OAuth 刷新 HTTP 500、OAuth REST 190303、未知业务错误、网络超时的回归用例。

## 6. 指定服务器必须完成的现场条件

以下是环境和配置前置条件，不是新增业务功能。

| 条件 | 需要现场确认的证据 |
|---|---|
| API 与 Worker 出口 | 两个容器发往腾讯的实际公网来源位于各应用允许的 IP 范围；不能仅看宿主机网卡或浏览器出口 |
| 入站 HTTPS | 回调域名、证书、443、防火墙、Nginx 到本机4522路径均有效 |
| Backend 路由 | context、principals/resolve 可返回真实启用员工；仅 /health 返回200不够 |
| 身份服务凭据 | Meeting 的 BACKEND_SERVICE_TOKEN 与 Backend 的 MEETING_IDENTITY_SERVICE_TOKEN 一致 |
| 组织成员映射 | member_id 来自 Backend 组织成员，不与 User.id、userid、open_id 混用 |
| 两类应用 | 企业应用 AK/SK 与 OAuth 客户密钥分别配置；测试人员、scope、open_corp_id 允许范围正确 |
| 事件配置 | 从网关 setup 获取 receiver_id 对应 URL，配置 Token、EncodingAESKey，订阅 common.sts-token 等所需事件 |
| 内部访问 | 内部应用、管理员或 VPN 的来源通过 Nginx 的内部网段限制 |
| 私有状态 | PostgreSQL、密钥、私有存储卷持久化；不以清空库或重置密钥解决授权问题 |
| 访问白名单 | 媒体及内部通知目标采用明确的允许域名/网段；不填写任意公共通配规则 |

腾讯官方的 IP 白名单限制是“来源请求”，OAuth 回调域名是另一项配置。部署到允许的出站 IP 不代表腾讯到你们回调入口的网络也自动可达。[T01]

首次 STS 生成返回 req_id，真正凭证通过 Webhook 到达，敏感接口后续携带 STS-Token。[T02][T03] 因此首轮企业内容联调不能只启动 API 而不启动 Worker。

对于还处于应用测试阶段的 OAuth 应用，需确认测试地址、调试人员及对应 scope；创建会议还受测试账号资源和调试调用限额影响。[T04] 这些不是所有来源拒绝都能靠添加 IP 白名单解决。

## 7. 推荐的最小部署与联调步骤

### G0 — 固定测试版本并检查环境

固定本报告 SHA，准备独立测试数据库与私有配置。建议在指定服务器执行以下检查；本轮未在该服务器执行：

```bash
# 已准备好真实私有 .env，且在 meeting-gateway 仓库根目录。
uv sync --frozen --group dev
uv run python -m app.cli check

docker compose --env-file .env -f deploy/compose.yaml config --quiet
```

`config --quiet` 不打印完整展开配置，避免将密钥带入共享日志。Dockerfile 未冻结依赖的问题应在正式镜像交付前修复，并保留实际镜像 digest。

### G1 — 启动基础服务

先通过 Compose 的迁移顺序启动数据库、迁移、API、Worker，再接入现场 Nginx 和 TLS。检查：迁移服务退出0；API可达；Worker持续运行且不重复出现 IDENTITY_SERVICE_UNAVAILABLE；/health/ready 数据库和Backend字段都满足预期；实际成员解析成功。

初始保持创建、MCP、企业全量同步、媒体下载、自动录制关闭。按测试阶段逐项启用和批准范围，不用全员全量开放绕过问题。

### G2 — 通过管理 HTTP 接口登记与诊断

可以用受控 HTTP 工具调用现有接口，不需要新建会议工作台：

```text
POST /api/v1/admin/bootstrap
POST /api/v1/admin/applications
POST /api/v1/admin/identity-bindings
POST /api/v1/admin/connections/enterprise
GET  /api/v1/admin/applications/{application_id}/setup
POST /api/v1/admin/connections/{connection_id}/diagnostics
```

这些接口使用真实 Backend 员工认证，并遵守网关 bootstrap/管理权限条件。不要直接在数据库插入管理员凭证或伪造员工信息。仅在已授权测试成员和指定资源范围内配置连接。

### G3 — 分别验证 AK/SK 与 OAuth 授权

企业路径：configuration -> history/records/corp_records 中适用的只读探测 -> Webhook challenge -> request STS -> 接收 common.sts-token -> 票据 ACTIVE -> 敏感文件探测。

OAuth 路径：授权启动 -> 腾讯回跳 -> PENDING_CONFIRMATION -> 同一员工调用确认接口 -> ACTIVE -> oauth_user_info -> 本人允许的会议读取。

验收不以连接记录写入 ACTIVE 或 HTTP 200 为唯一依据，需包含目标资源/身份确实对应、票据确实被调用等证据。

### G4 — 目标会议结果读取

选择一场腾讯端已经有录制、转写和指定纪要的非敏感会议。先用受控同步产生必要的本地资源映射，再读取转写与纪要；用 cache 明确读取现有企业会议，避免把已知 enterprise ensure 限制误判为腾讯拒绝。该绕行仅用于隔离诊断，不替代 F-01/F-03 的正式业务修复。

### G5 — 内部系统与智能体调用

完成 F-01 至 F-05 的对应业务范围后，再验收企业主通道、完整历史分页、按需录制、创建后结果回流及受控下载。OAuth TRUSTED_MEMBER 是当前已经实现的直接排队路径，可先用其验证内部应用创建，但不能据此宣称 AK/SK 创建也已实现。

MCP 最后复用相同服务，不把智能体接入作为第一次 Tencent 授权联调的先决条件。

## 8. 建议开发顺序与完成判据

| 批次 | 内容 | 完成判据 |
|---|---|---|
| D0 部署准备 | 真实身份合同、出口/回调网络、冻结镜像、配置及健康检查说明 | 目标服务器构建启动证据；实际 context/resolve；无凭据泄露 |
| D1 联调工具 | 替换占位 smoke/live test，先只读 | 指定服务器有实际 HTTP 请求、资源匹配断言和失败非零退出；无请求不能记PASS |
| D2 对内主通道 | 企业连接源查询/本人创建、USER_WINDOW 分页、ensure 正确分派 | 允许范围的 AK/SK 请求到达腾讯；拒绝范围零写入；分页与目标录制可核对 |
| D3 授权闭环 | 内部系统完成 OAuth 确认；HTTP错误分类恢复 | 不依赖 Portal UI 也能由可信员工完成授权；暂时500不错误撤销授权 |
| D4 页面与发布门禁 | Portal增量兼容、基线fixture、Ruff、镜像启动CI | 相关构建和门禁实际通过，跳过或阻断的在线项仍单独展示 |

D0 与只读人工联调可以先推进，D1–D3 同步开发。不能等待所有业务完善才开始验证白名单环境；也不能为了“先上机”把已知不支持的业务路径描述成已支持。

## 9. 证据与来源索引

所有仓库源文件链接均固定在本次 SHA；以下 URL 仅作核查依据。

- [R01] 分支基线：`https://api.github.com/repos/smc-copilot/meeting-gateway/branches/master`
- [R02] CI：`https://github.com/smc-copilot/meeting-gateway/actions/runs/38985761134`
- [R03] Python job：`https://github.com/smc-copilot/meeting-gateway/actions/runs/38985761134/job/117256737050`
- [R04] Portal job：`https://github.com/smc-copilot/meeting-gateway/actions/runs/38985761134/job/117256736871`
- [R05] 部署文件：固定 SHA 下 `Dockerfile`、`deploy/compose.yaml`、`deploy/nginx.conf.example`。
- [R06] 配置：固定 SHA 下 `app/core/config.py`、`app/cli.py`、`app/main.py`、`app/integrations/nodeskclaw_backend/client.py`。
- [R07] 双通道与业务：固定 SHA 下 `app/services/connection_service.py`、`query_service.py`、`operation_service.py`、`content_service.py`、`event_service.py`、`maintenance_service.py`。
- [R08] 路由：固定 SHA 下 `app/api/business.py`、`app/api/admin/router.py`、`app/api/portal.py`。
- [R09] 测试及工具：固定 SHA 下 `scripts/tencent_live_smoke.py`、`tests/live/test_tencent_live.py`、`tests/live/test_internal_consumer.py`、`tests/acceptance/test_phase1_gateway.py`、`tests/contracts/test_external_gates.py`。
- [R10] 上游错误：固定 SHA 下 `app/integrations/tencent_meeting/client.py`。
- [T01] 腾讯第三方应用配置：`https://meeting.tencent.com/support/topic/2162/index.html`
- [T02] 腾讯 STS 生成：`https://cloud.tencent.com/document/product/1095/127650`
- [T03] 腾讯 STS 事件：`https://cloud.tencent.com/document/product/1095/127651`
- [T04] 腾讯第三方应用测试：`https://meeting.tencent.com/support/topic/2163/`

R05–R10 对应完整源码基址：`https://github.com/smc-copilot/meeting-gateway/blob/e966bd90637fd2ae95635635596779be99cf29b8/`。

本报告的现场步骤都是待执行清单，不是已完成的服务器检查记录；CI 与本地隔离脚本证据已经与真实 Tencent 联调证据分开。
