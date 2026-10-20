---
title: "Meeting Gateway：账号登录、ENV 应用配置与 OAuth 会议数据提取解决方案 PRD"
prd_id: "PRD-MG-OAUTH-LOGIN-001"
version: "1.1.0"
template_version: "1.0"
status: "REVIEW"
product: "meeting-gateway"
repository: "https://github.com/smc-copilot/meeting-gateway"
branch: "master"
source_commit: "79e22d08b623a4f7816db05af631a463fe14348b"
owner: "项目产品与技术负责人（审批角色，非已签署记录）"
reviewers: ["网关开发负责人", "内部应用负责人", "腾讯会议管理员", "部署运维负责人"]
created_at: "2026-10-17"
updated_at: "2026-10-17"
target_release: "oauth-readonly-login-env.1"
change_type: ["BROWNFIELD_CHANGE", "ARCHITECTURE_CHANGE", "INTEGRATION", "MIGRATION", "BUGFIX"]
golden_consumer: "指定白名单服务器上的 meeting-gateway + meeting-integration-kit + 一个真实内部应用客户端"
related_docs: ["需求PRD工程模板.md", "meeting-gateway-腾讯会议部署授权与生态联调手册-20261017.md"]
supersedes: ["旧 PRD 中 Backend 三个身份接口的依赖", "OAuth 测试必须先配置 AK/SK 或 STS 的前置条件", "腾讯应用凭据必须经管理 API 手工登记的流程"]
---

# Meeting Gateway 解决方案 PRD

**目标链路：账号密码登录 → 网关本地会话 → `.env` 装载腾讯 OAuth 应用 → 员工授权腾讯会议 → 拉取会议、录制、转写与纪要 → 内部系统取回数据及本地导出。**

本文件是变更设计，不是现有功能完成声明。仓库事实固定到上述 SHA；用户给出的登录响应属于接口样例；未访问私网登录地址，未使用样例中的 Token，未执行真实腾讯调用。设计决策与源材料事实分别标注。公开在对话中的访问令牌、刷新令牌不进入本文或测试 fixture；运维应按原身份系统实际支持的撤销机制处理，不能假定重新登录即撤销旧令牌。

# 0. PRD 使用原则

## 0.1 文档职责

本文按附件模板第 0—36 章组织，定义目标、边界、状态、输入输出、副作用、失败、验收与证据。正文 §7—§19 是需求单元引用的合同，§10 的规范条款均标有 Acceptance 编号。§20 提供可执行判据，§27 建立追踪。配置名与新增路由均为**目标合同**，不得当作当前版本已支持的命令。

## 0.2 规范关键词

MUST 为验收必需，MUST NOT 为明确禁止，SHOULD 为默认建议且偏离留档，MAY 为不影响本轮主门禁的扩展。每条强制语句归入 §10 的需求与验收；§25 的交付门禁归入 REQ-EVID-001。

## 0.3 No-Inference Rule

对本文未定义、影响身份、授权、状态或副作用的分支，实施方记录 `SPEC_SEMANTIC_GAP`，暂停该需求计划生成，不自行扩大权限或更换外部接口。部署输入尚未填入不等于可以猜值；真实输入由运行绑定文件提供。本文的固定决策不因测试失败被暗改。

# 1. 文档元数据

| 项目 | 值 |
|---|---|
| PRD 状态 | REVIEW，未批准进入开发计划 |
| 代码分析来源 | master / 79e22d08b623a4f7816db05af631a463fe14348b |
| 服务器源码目录（用户指定） | `/data/projects/meeting-meeting` |
| 联调工具目录（用户指定） | `/data/projects/meeting-integration-kit` |
| 允许的 Backend 业务接口 | `POST http://192.168.102.247:4510/api/v1/auth/account-login` |
| 禁止的 Backend 接口 | `GET /api/v1/auth/meeting-context`；`POST /api/v1/internal/meeting/principals/resolve`；`POST /api/v1/internal/meeting/principals/search` |
| 本轮腾讯鉴权 | OAuth；无 AK/SK、STS、企业全量采集前置要求 |
| 已知应用信息 | 企业 ID `210022394`；应用 ID `33510141629`；Secret 由服务器管理员填写 |
| 已知腾讯白名单/回调配置 | 出口 IP `120.234.52.38`；已登记域名 `https://copilot.superic.com:9999`；仅作为现场输入，不证明连通 |
| 发布审批 | 技术、安全与业务负责人分别审核；本文不代替签署 |

# 2. 一句话目标

让内部系统的真实员工，在指定账号登录接口可达、腾讯 OAuth 应用已配置且测试资源获准访问的前提下，通过 Meeting Gateway 完成登录、腾讯用户授权和会议结果提取，同时保证三个旧身份接口调用次数为零、腾讯应用凭据从 `.env` 读取、任何失败不切换为企业管理员凭据。

# 3. 背景与问题定义

## 3.1 Current State（源代码事实）

| 事实 | 固定版本代码定位 | 对本次目标的影响 |
|---|---|---|
| Runtime 构造 `BackendClient`，依赖 Backend URL 与 service token | `app/runtime.py::Runtime.__init__` [SRC-02] | 仅修改部署文档不能去除依赖 |
| BackendClient.context/resolve/search 调用三个被禁止接口；ready 还请求 Backend `/health` | `app/integrations/nodeskclaw_backend/client.py` [SRC-03] | 需要替换适配器，并停止所有非登录的 Backend HTTP 请求 |
| 登录令牌交换和后续成员请求使用 backend.context/resolve | `app/services/auth_service.py` [SRC-04] | 不能继续接受 Backend JWT 并调用旧 context 核验 |
| 生产 Settings 强制要求 backend_service_token；没有本次拟定的腾讯 ENV 三字段 | `app/core/config.py` [SRC-05] | 删除服务凭据强制项；新增 ENV 合同与初始化 |
| OAuth 发起、回调、刷新含 backend.resolve；回跳默认 Portal；应用 return URI 列表来自 settings_data | `app/services/connection_service.py::oauth_start/oauth_callback/oauth_credentials` [SRC-06] | 替换成本地身份快照；消除 Portal 页面前置条件 |
| 源查询已包含历史分页与录制查询；`CORP_WINDOW` 被拒绝 | `app/services/query_service.py` [SRC-07] | 复用查询能力；OAuth 本轮不解除企业全量查询限制 |
| OAuth 当前企业核验要求 allowed_open_corp_ids；未知企业会被阻断 | `connection_service.py::oauth_callback/_confirm_oauth` [SRC-06] | 企业 ID 与 open_corp_id 不能强行视为相同 |
| 当前查询 `MEETING_ID` 捕获多类上游错误后统一转换 404；录制分支允许宽松上游结果进入 upsert | `query_service.py::run/_recordings` [SRC-07] | 新方案保留错误分类、校验指定资源，不靠隐藏故障通过测试 |

当前源码中已有数据库、密钥环、连接、访问授权、转写/纪要存储、Worker 等模块。本轮是这些模块的增量改造，不重新实现腾讯会议，不建立新的 OA 业务平台。上述“已有”表示代码存在；本文没有重新运行完整回归，亦不重用旧 CI 结果宣称本次变更通过。

## 3.2 Problem（可验证问题）

P-01：没有三个身份接口时，当前员工授权与令牌交换在请求腾讯前失败。

P-02：只向当前 `.env` 增加腾讯 ID/Secret，不会自动生成可用 OAuth Application；管理流程仍依赖旧身份接口。

P-03：给出的登录响应没有 OrgMembership.id、department、supervisor 等字段；不能用常识补成旧 MemberContext。

P-04：当前部署与工具流程把双通道、STS、完整 Portal 和历史全量门禁混入 OAuth 读取目标。

P-05：Backend 登录、网关本地会话、腾讯 OAuth 是三个不同凭证域；简单透传 Token 或把客户端提交的 user JSON 当真，会破坏身份边界。

## 3.3 Impact

业务：无法按“登录后读取本人获准的腾讯会议数据”完成单通道联调。

工程：Runtime、鉴权、回调、Worker、管理路由和测试都需要同一次身份切换，不能只改一个 client.py。

安全：只用登录接口后，Backend 停用变化不能实时查询；必须明确快照时效和本地撤权，而非声称无损等价。

运维：腾讯凭据改由 `.env` 管理，启动、变更、重启一致性、密钥轮换与旧数据处理需要确定规则。

Coding：将“账号登录即可”落成唯一请求、字段映射、本地 Session 与网络白名单，避免生成假 resolve 服务。

# 4. Scope

## 4.1 In Scope

| Scope | 内容 | Requirement |
|---|---|---|
| SCOPE-001 | 唯一 Backend 登录出站、禁止路径与运行面清理 | REQ-BOUNDARY-001 |
| SCOPE-002 | account/password 转发及登录响应验证 | REQ-AUTH-001 |
| SCOPE-003 | 本地身份、会话、管理员与权限 | REQ-ID-001 / REQ-AUTH-002 / REQ-ACL-001 |
| SCOPE-004 | ENV 应用装载、变更与持久化对账 | REQ-CONFIG-001 / REQ-CONFIG-002 |
| SCOPE-005 | OAuth 浏览器授权、公司核验、确认、刷新 | REQ-OAUTH-001 / 002 / 003 |
| SCOPE-006 | 内部客户端本地令牌交换 | REQ-CLIENT-001 |
| SCOPE-007 | 历史会议、录制、转写、纪要读取与导出 | REQ-QUERY-001 / 002 / REQ-CONTENT-001 / 002 / REQ-EXPORT-001 |
| SCOPE-008 | Worker、重试、迁移、部署、联调工具和证据 | REQ-JOB-001 / REQ-MIGRATE-001 / REQ-DEPLOY-001 / REQ-CMD-001 / REQ-EVID-001 |
| SCOPE-009 | 密码与令牌保护、出站及内容隔离 | REQ-SEC-001 |

## 4.2 Out of Scope

本 release 不执行：NON-GOAL-001 腾讯会议创建、修改、取消或修改录制权限；NON-GOAL-002 AK/SK 与 STS 联调；NON-GOAL-003 企业全量录制/会议接口；NON-GOAL-004 OA 写入、ASR、二次摘要生成、文档翻译；NON-GOAL-005 新员工目录和组织管理、冒充员工、无人值守企业采集；NON-GOAL-006 MCP/智能体创建与委托授权；NON-GOAL-007 必须部署整个 nodeskclaw 或 Portal；NON-GOAL-008 腾讯事件订阅和内部事件投递作为主验收前置项；NON-GOAL-009 自动下载全部原始音视频。

MCP、AK/SK、媒体、事件旧代码可以保留为未注册/关闭的兼容代码，但本运行模式的出站门禁拒绝对应请求；不是只隐藏页面。以上禁止项由 A-BOUNDARY-002、A-SEC-002 验证。

## 4.3 Architecture Boundary

| Domain | Owner | Input | Output | 不负责 |
|---|---|---|---|---|
| 需求 | 本 PRD / 产品负责人 | 用户限制和样例 | 边界与验收 | 猜测私网部署行为 |
| Spec | 网关技术负责人 | 本合同 | API/Schema 版本 | 修改用户指定接口 |
| Plan | 开发负责人 | 已批准 PRD | REQ/AC 关联任务 | 填补身份语义 |
| Execution | 网关服务 / Worker | 本地身份与 OAuth 授权 | 获准会议数据 | Backend 三个身份接口 |
| Governance | 审核/测试/运维 | 回执、日志、数据摘要 | PASS/FAIL/BLOCKED | 将 NOT_RUN 记成 PASS |
| 身份 | AccountLoginClient + 本地身份服务 | 唯一登录响应 | 本地身份快照与会话 | 请求 Backend 员工列表 |
| 应用配置 | ENV Loader | `.env` | 受管 OAuth 应用及私有凭据 | 腾讯控制台自动修改 |
| 腾讯内容 | TencentClient + 查询/内容服务 | Tencent OAuth 连接 | 原生转写/纪要 | 扩大 OAuth 数据范围 |

# 5. Terminology / Domain Model

| 术语 | 唯一含义 |
|---|---|
| BackendLogin | 网关使用 account/password 向指定私网接口发出的一次登录请求 |
| BackendUserID | 登录响应 `data.user.id`；本轮不把它称为 Backend member_id |
| GatewayMemberID | 本地生成的 UUID，用于兼容现有 member_id 主体字段；来源 `LOCAL_ACCOUNT_LOGIN` |
| LoginSnapshot | 经网关直接接收并校验的登录响应字段白名单，有观察时间和有效期 |
| GatewaySession | 本地不可推导的短期登录会话，不是 Backend JWT，不是腾讯 Token |
| ClientAccessToken | 网关按内部客户端、员工、scope 和会话签发的业务令牌 |
| TencentCorpID / TencentAppID | 应用所属企业 ID / 应用 ID；对应腾讯 corp_id / sdk_id |
| OpenCorpID | 腾讯 OAuth 返回的授权用户企业标识，不与内部 org_id 或应用 corp_id 自动等同 |
| OAuthConnection | 本地用户与指定腾讯应用下 open_id 的授权关系 |
| ENV_MANAGED | 应用及静态凭据由 ENV 装载器单一写入；管理 API 不能覆盖 |
| 本轮只读 | 禁止修改腾讯业务资源；本地会话、令牌、任务、缓存、导出和日志写入属于允许副作用 |
| 会议数据提取 | 实际取得会议元数据、录制元数据、完整转写及目标腾讯纪要，并可由内部系统/工具写成私有文件 |
| Implemented / Verified | 已写代码 / 对应验收具有本次执行证据，二者分离 |
| PASS / BLOCKED | Oracle 满足 / 缺少前置条件或真实证据；后者不能表示成功 |

# 6. System Context

## 6.1 Context Diagram

```text
员工 / 内部系统
  │ 账号密码（HTTPS）
  ▼
Meeting Gateway ── 唯一身份 HTTP ──> 192.168.102.247:4510
  │                                   POST /api/v1/auth/account-login
  ├─ 本地 Member / LoginSnapshot / Session / Client / ACL
  ├─ .env → ENV 管理的腾讯 OAuth 应用
  │
  ├─ 浏览器 → 腾讯 authorize → Gateway 公网 callback
  ├─ 腾讯 access_token / refresh_token / user_info
  └─ Worker → 腾讯历史/录制/转写/纪要 GET
       │
       ▼
PostgreSQL 元数据 + 私有加密正文
       │
       └─ 内部 REST → integration-kit 私有 JSON / TXT / Markdown + 脱敏证据
```

## 6.2 System Boundary

内部：本地身份映射、会话、授权、ENV 应用、查询、存储、结果、报告。外部：唯一 Backend 登录服务、腾讯授权/数据服务、用户浏览器、服务器网络设施。

可信输入：操作员在受限 `.env` 内设置的地址与凭据；网关直接从固定登录上游接收且通过 Schema 校验的响应；通过 state 核验并由腾讯换码得到的 OAuth 返回。

不可信输入：请求体中的 user/role/org_id、任意外部 Token、浏览器 query、腾讯会议正文中的指令、上传脚本与任意 return_to。会议正文只能作为数据，不能触发工具执行。

安全例外：用户指定 Backend 为明文 HTTP。该链路不提供传输加密。部署需显式设置 `BACKEND_LOGIN_ALLOW_HTTP=true`，记录受控内网/隧道与端口访问限制证据；不能把私网地址描述为等同 TLS。网关对外登录和腾讯交互保持 HTTPS。不额外访问私网 `/openapi.json`、`/health`、`/me` 来补资料。

# 7. Authoritative State / Source of Truth

| State | Role | Authoritative? | Writer | Reader | 可否自动覆盖 |
|---|---|---:|---|---|---|
| `.env` 中 app/secret/org/端点配置 | DESIRED_STATE | 是（静态配置） | 运维 | ENV Loader | 否，程序不改 `.env` |
| EnvApplicationProjection + 配置摘要 | LAST_APPLIED_STATE | 是（已应用版本） | ENV Loader | API/Worker | 同 identity、受管字段可事务更新 |
| LoginSnapshot | OBSERVED_STATE | 是（最近一次已校验观察） | 登录服务 | 本地权限服务 | 新的真实登录可更新 |
| LocalMember | RESOLVED_STATE | 是（网关主体映射） | 本地身份服务 | 全部业务路径 | 唯一映射；不从名称推断 |
| LocalMember.local_blocked | RUNTIME_STATE | 是（本地阻断） | 已认证管理员 | Session/Worker | 登录不清除此标记 |
| GatewaySession/ClientAccessToken | RUNTIME_STATE | 是（本地授权有效期） | 本地鉴权服务 | 路由/Worker | 到期/注销/版本变化拒绝 |
| OAuthConnection/TokenGeneration | RUNTIME_STATE | 是（腾讯授权有效状态） | OAuth 服务 | TencentClient | 按版本 CAS 更新 |
| AccessGrant/ResourceOrigin | RESOLVED_STATE | 是（本地访问边界） | 确认/权限服务 | 查询/下载/Worker | 指定 owner，不扩大到组织 |
| QueryJob + QueryResultItem + checkpoint | RUNTIME_STATE | 是（执行进度） | Worker | 接口/工具 | 租约 fence 合法写入 |
| Meeting/Recording/AssetVersion | OBSERVED_STATE | 是（本地已有数据） | 查询/内容服务 | 内部系统 | 按版本发布，不冒充实时全量 |
| evidence/run-id/manifest.json | EVIDENCE_STATE | 是（本次执行证据） | 测试工具 | 报告生成器 | 不覆盖其他 run |

“最近登录时 is_active=true”不是“Backend 现在仍启用”的事实；没有额外核验接口时不声称实时停用同步。当前权限由未过期快照与本地阻断共同决定。

# 8. State Machine

## 8.1 身份和会话

`未登录 → LOGIN_PENDING → ACTIVE / REJECTED`。成功前验证 `code=0`、有效 user.id/current_org_id、`is_active=true`、`must_change_password=false`、`needs_org_setup=false`、有效 expires_in。ACTIVE 在到期、注销或本地阻断后分别变为 EXPIRED、REVOKED、BLOCKED；旧会话不能由刷新 Backend Token 恢复。新登录创建新会话，更新同一个本地成员观察版本。HTTP200/code=0且身份字段完整、但明确is_active=false或must_change_password=true时，已存在同身份的成员可写入更严格阻断观察并撤销本地会话；不签发新会话。错误密码/网络失败不得依据未认证的user片段修改他人状态。

每个会话保存自己的不可延长 `identity_expires_at`。新登录不延长旧会话；同主体登录返回更低角色或禁用状态时，旧会话按更严格的本地状态失效。缺少字段不创建正常会话。

## 8.2 配置

`UNCONFIGURED → VALIDATED → APPLIED`；格式错误为 CONFIG_INVALID，受管 identity 冲突为 CONFIG_CONFLICT。同摘要重启无新增行；Secret 变化只更新静态密钥版本，不把腾讯已发 Token 标成“验证成功”。应用 ID、企业 ID、内部 org_id 或身份源变化，不自动接管旧数据。

## 8.3 OAuth

事务：`PENDING → EXCHANGING → RECEIVED / FAILED / OUTCOME_UNKNOWN`；state 默认 300 秒、一次性、绑定 session/member/application/config generation。换码调用前消费 state；超时不重放 auth_code，重新发起用户授权。

连接：`UNBOUND → PENDING_CORP_APPROVAL / PENDING_CONFIRMATION → ACTIVE`。空 OpenCorpID 在本企业测试模式为 CORP_REJECTED；非空但未列入允许列表保持 PENDING_CORP_APPROVAL。运维独立核对公司并将该精确 OpenCorpID 加入 ENV，应用配置生效后，原用户经 user_info 验证再确认，才能 ACTIVE。应用 CORP ID 不用于推算 OpenCorpID。

ACTIVE 可变为 DEGRADED（暂时故障）、REAUTH_REQUIRED（腾讯明确令牌失效）、REVOKED（本地主动解除）、BLOCKED（本地身份/配置冲突）。ACTIVE 不证明已读到会议正文。

## 8.4 查询、正文与导出

任务：`PENDING → RUNNING → SUCCEEDED | SUCCEEDED_EMPTY | RETRYING | WAITING_LOGIN | FAILED | CANCELLED`。媒体生成中到达任务等待期限则 `BLOCKED_CONTENT_NOT_READY`；不会永久每秒重试。WAITING_LOGIN 经同 owner/client 新会话调用 resume 后继续，禁止 Worker 保存密码重新登录。

正文：`ABSENT → FETCHING → PARTIAL → READY`；生成中为 NOT_READY，权限失效为 BLOCKED，达到保存期限为 EXPIRED。仅完整有效内容可发布 READY。READY 版本不可原地拼接其他版本的段落。

导出：`PLANNED → TEMP_WRITTEN → VERIFIED → COMMITTED`；失败不保留看似完整的目标文件。相同 run/内容摘要再次执行为幂等；不同字节同目标路径拒绝覆盖。

非法转移统一 `STATE_CONFLICT`；每个合法状态写入对应数据库表。故障与恢复的可观察结果见 §10 和 §23。

# 9. Data / Schema Contract

## 9.1 Schema Rule

对内输入 Schema 版本 `mg.oauth-readonly/1.1`；除显式兼容字段外 `additionalProperties=false`。Backend/腾讯响应属于外部 Schema：保留未知字段兼容，但只投影明确字段，未知值不能参加授权。所有时间为 UTC ISO8601 或明确标记的 UNIX 秒；腾讯录制毫秒字段按源单位转换。ID 对外一律字符串。

新 API、配置与响应字段均在本轮实现，现有源码不能直接照例调用成功。开发交付时更新 OpenAPI 和 integration-kit 契约版本；不仅修改文档。

## 9.2 ENV 配置合同

| Field | Type | Required | Default | Authority | Meaning |
|---|---|---:|---|---|---|
| MEETING_IDENTITY_MODE | enum | 是 | `account_login_only` | ENV | 本版本唯一身份模式，无旧 Backend fallback |
| BACKEND_ACCOUNT_LOGIN_URL | URL | 是 | 用户指定的固定登录 URL | ENV | 只允许 POST，禁止 query、fragment、userinfo、重定向 |
| BACKEND_LOGIN_ALLOW_HTTP | bool | 条件必填 | false | ENV | 仅对固定私网登录端点允许 HTTP；当前现场设 true 并记录风险 |
| MEETING_ALLOWED_ORG_ID | string | 是 | 无 | ENV | 限定本部署可接受的内部组织 |
| MEETING_ADMIN_USER_IDS | JSON string[] | 是 | 无 | ENV | 允许初始化/管理的 Backend user.id；不是目录查询结果 |
| MEETING_SESSION_TTL_SECONDS | int | 否 | 900，范围 60..3600 | ENV | 实际会话时长还受 expires_in 限制 |
| TENCENT_MEETING_AUTH_MODE | enum | 是 | `oauth` | ENV | 本版本只支持 OAuth 执行 |
| TENCENT_MEETING_CORP_ID | string | 是 | 无 | ENV | 腾讯应用所属企业 ID → tencent_corp_id / corp_id |
| TENCENT_MEETING_APP_ID | string | 是 | 无 | ENV | 腾讯应用 ID → sdk_id；不是企业 ID |
| TENCENT_MEETING_APP_SECRET | SecretStr | 是 | 无 | ENV | 腾讯 OAuth 客户密钥；不回显、不作为 AK/SK |
| TENCENT_MEETING_ALLOWED_OPEN_CORP_IDS | JSON string[] | 否 | [] | ENV | 精确允许的腾讯授权企业；空表允许进入待核验，不允许读数据 |
| TENCENT_MEETING_OAUTH_RETURN_URIS | JSON URL[] | 否 | [] | ENV | 可选内部页面的精确 return_to 白名单；不设置时用本地结果页 |
| TENCENT_MEETING_WEBHOOK_ENABLED | bool | 否 | false | ENV | 本 release 固定 false，HTTP 轮询即可完成主测试 |
| PUBLIC_BASE_URL | HTTPS origin | 是 | 无 | ENV | 构建 callback 和网关资源受众 |
| ALLOWED_HOSTS / CORS_ORIGINS | JSON string[] | 是/否 | 精确主机 / [] | ENV | 仅放行指定来源；无通配符 |
| DATABASE_URL / KEYRING_JSON / ACTIVE_KEY_ID | 私有配置 | 是 | 沿用现有格式 | ENV | PostgreSQL 与私有令牌/正文加密；不删除该安全依赖 |
| STORAGE_PATH | absolute path | 否 | `/data/private` | ENV | 私有正文目录，API/Worker 共用 |
| MEETING_CREATE_ENABLED / MEETING_CORP_SYNC_ENABLED / MEETING_MCP_ENABLED / MEETING_AUTO_RECORD_ENABLED / MEETING_MEDIA_DOWNLOAD_ENABLED | bool | 否 | 全 false | ENV | 在本 mode 下配置 true 返回 MODE_CONFLICT，不悄悄开启 |
| NODESKCLAW_BACKEND_URL / BACKEND_SERVICE_TOKEN / MEETING_IDENTITY_SERVICE_TOKEN | 已废弃 | 否 | 不读取 | 旧配置 | 本模式存在非空旧依赖变量时配置校验返回 DEPRECATED_IDENTITY_CONFIG，列字段名不列值 |
| PORTAL_BASE_URL | 已废弃前置项 | 否 | 无 | 旧配置 | 不再作为登录/回跳/启动必填；保留值不触发连接 Portal |

目标 `.env` 示例（管理员 ID 与组织 ID 来自用户给定响应；Secret 和网关域名需现场填写）：

```dotenv
MEETING_IDENTITY_MODE=account_login_only
BACKEND_ACCOUNT_LOGIN_URL=http://192.168.102.247:4510/api/v1/auth/account-login
BACKEND_LOGIN_ALLOW_HTTP=true
MEETING_ALLOWED_ORG_ID=2be7c618-326d-4a73-91ea-1cfda10f7073
MEETING_ADMIN_USER_IDS=["55576b5f-5be6-4a20-aca8-5b5526adf18a"]
MEETING_SESSION_TTL_SECONDS=900
TENCENT_MEETING_AUTH_MODE=oauth
TENCENT_MEETING_CORP_ID=210022394
TENCENT_MEETING_APP_ID=33510141629
TENCENT_MEETING_APP_SECRET=<仅在服务器私有.env填写真实客户密钥>
TENCENT_MEETING_ALLOWED_OPEN_CORP_IDS=[]
TENCENT_MEETING_OAUTH_RETURN_URIS=[]
TENCENT_MEETING_WEBHOOK_ENABLED=false
PUBLIC_BASE_URL=https://<现场已确认由网关承载的主机和端口>
ALLOWED_HOSTS=["<上项主机名>","127.0.0.1","localhost"]
CORS_ORIGINS=[]
MEETING_CREATE_ENABLED=false
MEETING_CORP_SYNC_ENABLED=false
MEETING_MCP_ENABLED=false
MEETING_AUTO_RECORD_ENABLED=false
MEETING_MEDIA_DOWNLOAD_ENABLED=false
# DATABASE_URL、KEYRING_JSON、ACTIVE_KEY_ID 沿用私有部署文件；不粘贴到报告。
```

不能把已登记的 `copilot.superic.com:9999` 直接占用为网关：先确认现有服务、证书和路由；若复用同一 origin，反向代理仅新增网关必要路径且不破坏原路由。独立域名需要腾讯后台相应回调配置。网络是否已生效以现场证据为准。[USR-02]

## 9.3 账号登录输入及外部响应

网关新增入口：`POST /api/v1/auth/account-login`。请求只接受：

```json
{"account":"<员工账号>","password":"<交互输入，不保存>"}
```

账号、密码各 1..200 字符，禁止自动 trim 密码。上游请求名 `{account,password}` 来自已检查的 nodeskclaw 历史 Schema [SRC-08]，不是从用户响应推导；私网部署实际版本未提供。若现场返回 422/不同 Schema，则记录 `LOGIN_CONTRACT_MISMATCH`，不尝试其他登录/用户接口，不自动猜 `username`、`email` 字段。

| Backend 响应字段 | 本地处理 | 缺失/错误行为 |
|---|---|---|
| `code` | 必须为数值 0，且 HTTP200 | 拒绝登录 |
| `data.expires_in` | 正整数，作为登录证据时效上界 | LOGIN_RESPONSE_INVALID |
| `data.user.id` | 作为 backend_user_id | 空值拒绝 |
| `data.user.current_org_id` | 等于 MEETING_ALLOWED_ORG_ID | 空值/跨组织拒绝 |
| `data.user.is_active` | 必须明确 true | false 拒绝，不能默认 true |
| `data.user.must_change_password` | 必须明确 false | true/缺失拒绝；原系统处理改密 |
| `data.needs_org_setup` | 必须明确 false | true/缺失拒绝；原系统处理组织初始化 |
| `data.user.portal_org_role` | string 或 null；仅 `admin` 是上游组织管理观察值 | null 视为无管理观察值 |
| `data.user.role` | 展示/记录，不决定网关管理 | `user` 不否定 portal_org_role=admin |
| `data.user.org_role` | 可空；不覆盖 portal_org_role | null 不降级有效 portal_org_role |
| `data.user.is_super_admin / is_task_admin` | 可记录必要状态，不授予会议数据权限 | `is_task_admin=true` 不是会议管理员 |
| `data.user.username / name` | 身份展示，非唯一键 | 缺失显示 backend_user_id |
| `access_token / refresh_token` | 只识别 envelope，不透传、不落库、不写日志；处理后丢弃 | 不解 JWT 取身份，不要求共享签名密钥 |
| email / phone / avatar_url / oauth_connections / provider | 不用于本轮授权；默认不保存 | 不补查目录 |

用户样例证实：返回 `user.id` 和 `current_org_id`，`role=user`、`portal_org_role=admin`、`org_role=null` 可以并存，且没有 Backend OrgMembership.id。[USR-01] 本地新建 GatewayMemberID；与 BackendUserID 的映射单独持久化。

**传输事实限制：**只能判断登录响应表达的状态，无法证明私网 Backend 内部是否另有强制改密或组织停用策略。不会额外发被禁止的请求“弥补”该不确定性。[SRC-08] 现场验收核实输出契约。

## 9.4 本地 Schema

| Schema ID / version | 必填字段、枚举、默认 | 兼容和迁移 |
|---|---|---|
| `LocalMember/1` | id(UUID)、identity_source_id、backend_user_id、org_id、name、username、portal_org_role、last_login_at、snapshot_expires_at、local_blocked=false、version、deleted_at | 活跃唯一键 `(identity_source_id,org_id,backend_user_id)`；不接管旧 member_id |
| `LoginSnapshot/1` | id、member_id、login_request_id、received_at、login_started_at、expires_in、validation_result、允许字段白名单 | 不含密码与上游令牌；观察记录追加 |
| `GatewaySession/1` | id、token_hash、member_id、snapshot_id、issued_at、expires_at、revoked_at、session_version | token 随机32字节；摘要存库；无 refresh |
| `ClientAccessToken/1.1` | 复用 AccessToken + login_session_id、identity_source=`ACCOUNT_LOGIN` | 有效期不得超过父会话；旧来源令牌失效 |
| `EnvApplicationProjection/1` | managed_key=`tencent-default`、org_id、application_id、identity_digest、config_hmac、generation、applied_at、owner=`ENV` | 保留原 Application.id；只写受管字段 |
| `OAuthConnection/1.1` | 应用、本地 owner member_id、open_id、open_corp_id、scopes[]、status、token_generation、confirmed_at | 同应用同 open_id 活跃归属唯一；不能以名字合并 |
| `QueryJob/1.1` | owner_member_id、client_id、login_session_id、connection_id、query、progress、state、lease_token | 在原 SyncJob 增加身份来源/暂停状态；旧作业暂停 |
| `QueryResultItem/1` | job_id、resource_kind、local_resource_id、provider_id、ordinal | 活跃唯一 `(job_id,resource_kind,local_resource_id)` |
| `Asset/1.1` | 复用原资产 + provenance、consistency、query_job_id、complete、content_hash | 历史版本不原地改正文 |
| `Evidence/1.1` | run_id、req/ac/test、sha、command_template、exit_code、oracle、files/digests、started_at、finished_at、redaction_policy | 不接受只有 PASS 字符串的记录 |

未知 JSON 字段对外输入拒绝；对外部响应只投影白名单。每个业务表使用软删除、活跃唯一索引；密文文件按到期策略清理，不声称数据库物理删除。

## 9.5 对内 API 合同

| 路径 | 鉴权 | 本轮语义 / 响应 |
|---|---|---|
| `POST /api/v1/auth/account-login` | 无本地令牌，限流 | 唯一上游登录；返回本地 session_token 与白名单用户信息 |
| `GET /api/v1/auth/session` | GatewaySession | 只读本地当前会话；不访问 Backend |
| `POST /api/v1/auth/logout` | GatewaySession | 本地撤销会话及子 token；不请求 Backend logout |
| `GET /api/v1/admin/runtime-config` | 本地管理员会话 | 字段名、非敏感 ID、secret_configured、generation；不回显 Secret/摘要 |
| `GET /api/v1/admin/applications/{id}/setup` | 本地管理员会话 | 返回 OAuth callback/默认结果页；不要求 webhook/STS 配置 |
| `POST /api/v1/admin/clients` | 本地管理员会话 | 仅 CONFIDENTIAL、非 service、非 agent；scope 限读 |
| `POST /api/v1/auth/exchange` | client_id+client_secret+subject_token | subject_token 改为本地 GatewaySession；拒绝 Backend JWT |
| `GET /api/v1/me/connections` | 本地会话或业务 token | 返回本人连接及公司审批/授权状态 |
| `POST /api/v1/oauth/authorizations` | 本地会话或业务 token | application_id 可省略取 ENV 默认；return_to 可省略；返回 URL/state 事务 ID |
| `GET /api/v1/oauth/authorizations/{id}` | 同 owner 会话 | 返回事务状态、connection_id；不返回 Token/code |
| `GET /callbacks/tencent/oauth/{application_id}` | state 事务验证 | 公网回调；换码结果落库；303 到已允许结果页 |
| `GET /oauth/tencent/result` | 无；静态说明页 | 无敏感数据、无第三方脚本，仅说明回到原客户端查看结果 |
| `POST /api/v1/connections/{id}/confirm` | 同 owner 会话/token | company 精确允许、user_info open_id 一致后 ACTIVE |
| `POST /api/v1/connections/{id}/revoke` | 同 owner 会话/token | 本地撤权；不伪造腾讯远端解除授权 |
| `POST /api/v1/meeting-queries` | 内部客户端业务 token | selection=USER_WINDOW / USER_RECORDINGS / RECORDINGS；CORP_WINDOW 409拒绝；生成作业202 |
| `GET /api/v1/jobs/{id}` | 作业 owner+client | 状态/进度；SUCCEEDED 与 SUCCEEDED_EMPTY 分开 |
| `GET /api/v1/jobs/{id}/results` | 作业 owner+client | `kind=meetings|recordings`；分页本次结果而非全部目录 |
| `POST /api/v1/jobs/{id}/resume` | 同 owner+client 新会话子token | 仅 WAITING_LOGIN，重新授权检查后恢复；正文检查点不清空 |
| `GET /api/v1/meetings` | 业务 token | 本地授权目录；支持 connection_ref/provider_meeting_id 精确过滤 |
| `GET /api/v1/meetings/{id}` | 业务 token | 默认 cache；不强制调用腾讯仅限 OAuth 创建会议的详情接口 |
| `GET /api/v1/meetings/{id}/recordings` | 业务 token | ensure 调录制查询而非详情查询；cache 只读现存 |
| `GET /api/v1/recordings/{id}/transcript` | 业务 token | ensure 异步获取；READY 返回分页完整版本 |
| `GET /api/v1/recordings/{id}/minutes` | 业务 token | ensure 异步获取；READY 返回腾讯原文 Markdown |
| `GET /health/live`、`GET /health/ready` | 网络限定 | 只查本进程/DB/已应用配置；不请求 Backend health 或自动登录 |
| 旧 `/api/v1/portal/*`、Backend JWT exchange、`/oauth/token` 的下游刷新/服务授予 | 不适用 | 本模式 410 `AUTH_FLOW_REPLACED`，不回退旧身份流程 |
| 创建/取消/STS/企业采集/MCP 入口 | 不适用 | 403 `READONLY_MODE` 或 409 `MODE_UNSUPPORTED`，不发生上游请求 |

`POST /api/v1/admin/applications` 与 credentials PUT 对 ENV_MANAGED 应用返回 409 `ENV_MANAGED_RESOURCE`。静态应用只从 ENV 配置；用户授权 Token 仍由 OAuth 回调/刷新维护，不能放入 `.env` 充当固定授权。

成功 envelope 保留 `code=0,error_code=null,message_key=null,message='success',data,trace_id`。错误增加稳定字符串 `reason`，不把上游错误消息或 URL原样返回。HTTP202仅表示受理。

## 9.6 核心请求与响应示例（目标合同）

```json
{
  "code": 0,
  "data": {
    "session_token": "<仅首次响应交付的网关随机会话值>",
    "token_type": "Bearer",
    "expires_in": 900,
    "user": {
      "backend_user_id": "<已校验登录响应的user.id>",
      "gateway_member_id": "<网关生成UUID>",
      "org_id": "<已校验current_org_id>",
      "portal_org_role": "admin",
      "identity_source": "ACCOUNT_LOGIN",
      "identity_fresh_until": "<UTC时间>"
    }
  }
}
```

```json
{
  "selection": "USER_RECORDINGS",
  "connection_ref": "<本人OAuth连接UUID>",
  "start_at": "2026-10-10T00:00:00Z",
  "end_at": "2026-10-17T00:00:00Z"
}
```

请求窗口默认最近7天，显式窗口最大366天；按历史90天、录制31天上游约束拆分；每页20。窗口切片交界可以重复请求边界秒，用 provider ID 去重；源时间筛选语义由腾讯接口决定，不假定所有字段单位相同。超过100000个逻辑结果或10000页，任务失败 `RESULT_LIMIT_EXCEEDED`，保留进度，不标完成。[WEB-02/03]

已有字段 `target_member_id` 如提交只能等于本地会话 member_id；`MEETING_ID` 单独上游详情不作为主流程前置。通过历史或录制返回元数据建立本地映射后即可读内容。对外结果新增 provider_meeting_id/provider_record_file_id，令脚本能核对真实样本而不是靠会议标题猜 ID。

## 9.7 错误合同

| reason | HTTP/任务行为 | 是否重新请求 |
|---|---|---|
| LOGIN_REJECTED / MEMBER_INACTIVE / PASSWORD_CHANGE_REQUIRED | 401/403，不签发 | 用户主动修正后登录 |
| LOGIN_RESPONSE_INVALID / LOGIN_CONTRACT_MISMATCH | 502，不签发 | 合同校正后再试 |
| LOGIN_UPSTREAM_UNAVAILABLE | 503，不重试密码请求 | 用户主动再提交 |
| LOGIN_RATE_LIMITED | 429 | 60秒窗口后 |
| ORG_NOT_ALLOWED / ORG_SETUP_REQUIRED | 403 | 原系统处理，不额外调用 |
| SESSION_EXPIRED / LOGIN_REQUIRED | 401；任务 WAITING_LOGIN | 同人重新登录后显式 resume |
| BACKEND_ENDPOINT_FORBIDDEN | 本地阻断，0网络请求 | 不重试 |
| CONFIG_INVALID / CONFIG_CONFLICT / DEPRECATED_IDENTITY_CONFIG | 配置检查退出非零；ready503 | 运维处理 |
| ENV_MANAGED_RESOURCE / IDENTITY_MIGRATION_REQUIRED | 409，禁止覆盖 | 完成离线迁移/配置修正 |
| STATE_INVALID / IDENTITY_CONFLICT | 400/409，拒绝绑定 | 新授权或人工核对 |
| OAUTH_CORP_APPROVAL_REQUIRED / OAUTH_CORP_REJECTED | 409/403 | 加精确允许企业后本人确认；空企业不接受 |
| UPSTREAM_REAUTH_REQUIRED | 409；连接 REAUTH_REQUIRED | 腾讯重新授权 |
| UPSTREAM_PERMISSION_DENIED / UPSTREAM_CAPABILITY_UNAVAILABLE | 403/409；非重试失败 | 腾讯权限/样本范围核对 |
| UPSTREAM_UNAVAILABLE / UPSTREAM_CLOCK_SKEW / RATE_LIMITED | 暂停或有限退避 | 按 §16.4 重试规则 |
| CONTENT_NOT_READY / CONTENT_ABSENT | 409；分别等待/确认无内容 | 不当作成功正文 |
| UPSTREAM_CONTRACT_ERROR / SOURCE_CHANGED | 502；保持非READY | 记录脱敏字段结构 |
| RESOURCE_NOT_ACCESSIBLE / TOKEN_INVALID / AUDIENCE_MISMATCH | 404/401 | 不换凭据 |
| READONLY_MODE / MODE_UNSUPPORTED | 403/409，0业务写出站 | 本 release 不执行 |
| EXPORT_CONFLICT / PATH_NOT_ALLOWED / EVIDENCE_INCOMPLETE | 非零退出 | 人工修正路径/证据 |

上游返回非授权错误不统一改为404。外部资源身份泄漏风险由当前资源权限检查和脱敏响应解决，运维证据仍保留经过白名单筛选的错误码。

# 10. Requirement Unit

所有需求按以下完整结构实施。每个需求至少一个正向和一个负向 Acceptance。符号及文件路径区分“现有修改”和“新增”；不存在的拟建符号不是已实现声明。

## REQ-BOUNDARY-001 — 唯一 Backend 登录接口与 OAuth 只读出站

### Goal
彻底移除三个身份接口依赖，而不是只在配置中隐藏。

### Normative Requirement
- MUST：将身份出站限制为固定 origin 的 POST /api/v1/auth/account-login；调用发生于用户明确登录请求，HTTP 不继承代理、不跟随重定向。API、Worker、健康检查、回调、后台维护、管理与工具均使用同一限制；Tencent 侧只开放 §17 的 OAuth 与读取操作。 [A-001, A-002]
- MUST NOT：调用三个旧身份路径、Backend /health、/me、/refresh、/logout、目录 API；或以其他 host/path 编码、代理、重定向绕过限制；构造假的 context/resolve/search 服务。 [A-002]

### Inputs
ENV 固定登录地址；规范化后的 method/origin/path；路由与 Worker 所有出站。

### Preconditions
PRE-001：配置校验通过；读取任务必须已具备本地会话。

### Authoritative State
ENV 登录地址为 DESIRED；NetworkPolicy 为 RESOLVED；脱敏出站计数为 OBSERVED。

### State Transition
允许请求 → 发出一次；禁止请求 → DENIED，网络调用计数保持不变。

### Allowed Side Effects
ALLOW：固定登录请求、腾讯允许列表请求、脱敏审计计数。

### Forbidden Side Effects
DENY：任意 Backend 备用端点；腾讯创建/修改/企业采集/STS；发出真实禁止请求来测试是否会拒绝。

### Ownership Scope
FILE：Runtime/适配器注册；ENTRY：出站规则；NONE：Backend 业务资源。

### Idempotency
相同配置重复构造不会增加备用调用；登录请求不自动重试。

### Failure Semantics
F-001 禁止路径→BACKEND_ENDPOINT_FORBIDDEN，0网络；F-002 重定向→LOGIN_UPSTREAM_UNAVAILABLE，0第二跳；无状态业务回滚。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
全部非登录阶段 Backend HTTP 计数=0，三个旧端点在整个运行期间计数=0。

### Invariants
INV-001：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-001, A-002；定义见 §20。

### Evidence
required test：TEST-A-001, TEST-A-002；required artifact：`evidence/<run_id>/REQ-BOUNDARY-001/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：app/runtime.py；app/integrations/nodeskclaw_backend/client.py（退出运行）；新增 app/integrations/account_login/client.py 与 network_policy.py；app/main.py；app/worker.py。

## REQ-AUTH-001 — 账号密码登录响应校验

### Goal
只使用真实登录返回的用户信息，不接收调用方自报身份。

### Normative Requirement
- MUST：实现 §9.3 输入/输出白名单、成功条件与错误映射；账号登录仅网关服务端发起；登录失败不签发本地会话。 [A-003, A-004]
- MUST NOT：接收客户端提交的 user JSON、把Backend JWT解码作为已验证身份、共享Backend JWT_SECRET、持久化密码或上游 access/refresh token。 [A-004]

### Inputs
account、password；上游HTTP状态及JSON；§9.3字段。

### Preconditions
PRE-001：固定登录端点；受控HTTP例外或TLS成立。

### Authoritative State
上游直接响应为OBSERVED；本地白名单快照为持久证据；客户端身份字段不可信。

### State Transition
LOGIN_PENDING → ACTIVE/REJECTED；得到上游成功但本地事务失败→无本地会话。

### Allowed Side Effects
ALLOW：一次上游POST；一个白名单快照/成员记录/会话事务；失败审计。

### Forbidden Side Effects
DENY：密码、上游Token、返回整个登录JSON到日志或外部调用方。

### Ownership Scope
ROW：本地登录数据；NONE：上游账号。

### Idempotency
每次用户主动成功登录新建会话；不重复创建同用户成员；密码POST无重试。

### Failure Semantics
F-001 4xx/非0→LOGIN_REJECTED；F-002 缺字段/422→LOGIN_RESPONSE_INVALID/LOGIN_CONTRACT_MISMATCH；F-003 超时→LOGIN_UPSTREAM_UNAVAILABLE；签发行0。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
登录样例中的role=user不覆盖portal_org_role=admin；空org_role合法；Backend原始Token不落入任何持久文件/数据库/日志；程序不保存其副本。

### Invariants
INV-002：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-003, A-004；定义见 §20。

### Evidence
required test：TEST-A-003, TEST-A-004；required artifact：`evidence/<run_id>/REQ-AUTH-001/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：新增 app/api/account_login.py；新增 app/services/account_login_service.py；新增 app/schemas/account_login.py。

## REQ-ID-001 — 本地用户标识及组织映射

### Goal
登录响应没有 Backend member_id，避免把两个不同ID混用。

### Normative Requirement
- MUST：按(identity_source_id,org_id,backend_user_id)生成并持久化独立UUID作为GatewayMemberID；Principal.user_id保存BackendUserID，Principal.member_id仅指本地UUID。采用数据库活跃唯一索引并发去重。 [A-005, A-006]
- MUST NOT：按姓名、邮箱、账号字符串猜OrgMembership.id；把BackendUserID直接覆盖旧member_id；通过身份搜索补查。 [A-006]

### Inputs
已校验LoginSnapshot；固定MEETING_ALLOWED_ORG_ID。

### Preconditions
PRE-001：REQ-AUTH-001通过；数据库唯一约束已迁移。

### Authoritative State
LocalMember为RESOLVED；user.id/current_org_id来自OBSERVED。

### State Transition
首次登录→新LocalMember；再次登录→同ID更新观察；跨组织→拒绝。

### Allowed Side Effects
ALLOW：本地成员及快照行；版本计数。

### Forbidden Side Effects
DENY：远端用户修改、跨组织迁移、旧资源静默改owner。

### Ownership Scope
ROW：LocalMember；FIELD：Principal映射。

### Idempotency
同组三元键始终同本地UUID；并发成功登录至多1个活跃成员。

### Failure Semantics
F-001 跨org→ORG_NOT_ALLOWED，映射0新增；F-002 并发唯一冲突→读取已有映射；F-003 旧ID无法证实→IDENTITY_MIGRATION_REQUIRED。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
返回gateway_member_id与backend_user_id两个明确字段，任何需要owner的请求以本地会话确定。

### Invariants
INV-003：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-005, A-006；定义见 §20。

### Evidence
required test：TEST-A-005, TEST-A-006；required artifact：`evidence/<run_id>/REQ-ID-001/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：新增 app/models/local_identity.py；app/core/types.py；permission/admin/connection 等主体关联。

## REQ-AUTH-002 — 本地短期会话、注销与时效

### Goal
后续API和Worker不再向Backend逐次解析成员，同时约束状态陈旧窗口。

### Normative Requirement
- MUST：登录签发随机本地会话；expires_at=min(login_started_at+上游expires_in,login_started_at+配置TTL)，默认900秒；每次本地请求检查会话到期、local_blocked、最新更严格角色及撤销状态；新登录不延长旧会话。 [A-007, A-008]
- MUST NOT：后台保存密码自动登录、刷新Backend令牌、对旧JWT只解码不验签放行、在会话失效后继续任务；声称Backend停用实时同步。 [A-008]

### Inputs
GatewaySession、LocalMember、当前UTC时间、撤销记录。

### Preconditions
PRE-001：登录成功；本地时钟和数据库时间可用。

### Authoritative State
Session为RUNTIME；快照只证明登录时状态；本地block优先。

### State Transition
ACTIVE→EXPIRED/REVOKED/BLOCKED；新登录生成独立ACTIVE；注销级联失效子token。

### Allowed Side Effects
ALLOW：本地会话及子令牌状态；本地审计。

### Forbidden Side Effects
DENY：Backend refresh/logout/resolve；刷新旧会话期限。

### Ownership Scope
ROW：session/token/member.block。

### Idempotency
重复注销成功但不多写授权；过期拒绝不新建会话。

### Failure Semantics
F-001 到期→SESSION_EXPIRED；F-002 身份本地阻断→MEMBER_INACTIVE；F-003 Backend不可用时旧会话仅在原截止之前按本地快照可用。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
停用风险上界为当前会话剩余期限；本地撤销对下一次请求生效；不追回已发出的字节。

### Invariants
INV-004：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-007, A-008；定义见 §20。

### Evidence
required test：TEST-A-007, TEST-A-008；required artifact：`evidence/<run_id>/REQ-AUTH-002/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：app/services/auth_service.py；新增 local_identity_service.py；app/api/deps.py。

## REQ-ACL-001 — 本地管理权与本人资源访问

### Goal
保持员工权限，不为去除Backend依赖而改成全能Key。

### Normative Requirement
- MUST：本地管理员须登录user.id在ENV管理名单且portal_org_role=admin、组织匹配；管理与正文权限分离。OAuth确认后仅给owner生成连接范围的meeting.read/meeting.content.read/meeting.content.download访问授权。搜索仅查本部署已登录成员。 [A-009, A-010]
- MUST NOT：以is_task_admin、role=user或is_super_admin自动给企业数据权；管理员读取其他员工正文；将同名腾讯用户自动绑定。 [A-010]

### Inputs
LocalMember、ENV管理员ID、连接owner、AccessGrant/ResourceOrigin/客户端scope。

### Preconditions
PRE-001：本地会话有效；已确认OAuth连接才能生成访问授权。

### Authoritative State
本地ACL为RESOLVED；角色只是管理条件，腾讯scope是上游权限边界。

### State Transition
连接确认→生成owner范围grant；本地撤销/禁用→后续请求拒绝。

### Allowed Side Effects
ALLOW：本地授权与管理日志；不创建后台采集身份。

### Forbidden Side Effects
DENY：全组织内容默认授权、跨connection复用token。

### Ownership Scope
ROW：owner授权；FIELD：来源范围。

### Idempotency
同连接重复确认不重复授权；重启不扩大范围。

### Failure Semantics
F-001 外人资源→RESOURCE_NOT_ACCESSIBLE；F-002 管理名单不符→PERMISSION_DENIED；F-003 撤权后缓存读取仍拒绝。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
A能读A获准资源；B即使有自己的有效业务token也不能读A；管理员权限不能覆盖上游拒绝。

### Invariants
INV-005：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-009, A-010；定义见 §20。

### Evidence
required test：TEST-A-009, TEST-A-010；required artifact：`evidence/<run_id>/REQ-ACL-001/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：app/services/admin_service.py；permission_service.py；portal_service.py（停止远端search）；新local_identity_service.py。

## REQ-CONFIG-001 — ENV 静态腾讯应用装载

### Goal
企业ID、AppID、Secret直接配置.env即可开始OAuth，不经手工应用登记。

### Normative Requirement
- MUST：实现 §9.2 固定命名、类型校验和AppId→sdk_id映射；启动单独的env-apply阶段创建ENV_MANAGED默认OAuth应用；无Webhook密钥、AK/SK或Backend服务Token也可通过此模式配置校验。 [A-011, A-012]
- MUST NOT：仅写.env却无代码读取；使用Secret构造AK/SK；把腾讯授权access/refresh token当静态.env配置；强制填写Webhook/STS。 [A-012]

### Inputs
.env / 显式注入进程环境；org ID；密钥环。

### Preconditions
PRE-001：迁移完成；ENV必填项非空；HTTP例外明确；路径权限受控。

### Authoritative State
ENV是DESIRED；Application投影是LAST_APPLIED；Secret运行内存来自ENV。

### State Transition
UNCONFIGURED→VALIDATED→APPLIED；未知字段/冲突→配置错误。

### Allowed Side Effects
ALLOW：受管应用元数据、config generation、必要密钥加密记录（不做配置真源）；不调用Tencent。

### Forbidden Side Effects
DENY：覆盖.env；创建个人OAuth Token；外部网络初始化。

### Ownership Scope
ENTRY：tencent-default受管应用；FIELD：静态配置。

### Idempotency
同ENV重复apply/多实例启动保留同application UUID，活跃应用数1。

### Failure Semantics
F-001 缺Secret→CONFIG_INVALID；F-002 废弃强依赖变量→DEPRECATED_IDENTITY_CONFIG；F-003 同sdk已存在非ENV所有者→CONFIG_CONFLICT。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
调用runtime-config可得非敏感ID、secret_configured=true；无法取得真实Secret；员工可发起默认应用授权。

### Invariants
INV-006：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-011, A-012；定义见 §20。

### Evidence
required test：TEST-A-011, TEST-A-012；required artifact：`evidence/<run_id>/REQ-CONFIG-001/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：app/core/config.py；app/cli.py；app/runtime.py；新增 env_application_service.py；app/models/applications.py；deploy/compose.yaml。

## REQ-CONFIG-002 — 配置版本、漂移与密钥变更

### Goal
保证.env是单一配置来源且重启不丢用户授权。

### Normative Requirement
- MUST：配置变更先校验、加应用锁、事务对账；同identity允许Secret与精确OpenCorp允许列表更新，记录内部HMAC版本；API/Worker本地配置摘要不等于已应用版本时拒绝相关业务，等待重启一致。 [A-013, A-014]
- MUST NOT：管理API覆盖ENV字段；identity变化时复用原OAuth Token；将旧Secret明文或普通摘要放报告；启动时重新生成加密密钥。 [A-014]

### Inputs
ENV配置、Projection、当前Application和TokenGeneration。

### Preconditions
PRE-001：具备旧密钥可解密已有数据；配置变更已备份；单次app锁。

### Authoritative State
ENV为DESIRED，Projection为LAST_APPLIED；OAuthToken为RUNTIME不由ENV重置。

### State Transition
同摘要→NO_CHANGE；同identity变更→generation+1；identity不同→CONFIG_CONFLICT且停用该配置应用执行。

### Allowed Side Effects
ALLOW：受管字段事务更新；旧凭据保留加密版本供回滚；连接能力验证时间失效。

### Forbidden Side Effects
DENY：自动接管手工应用或改org、改owner；记录Secret明文。

### Ownership Scope
FIELD：ENV受管字段；ROW：Projection和凭据generation。

### Idempotency
同修改重复apply不重复generation；Secret修改不新建connection。

### Failure Semantics
F-001 事务失败→Projection/受管字段=T0；F-002 回滚失败→保留恢复包、readiness503；F-003 runtime摘要不符→CONFIG_DRIFT，0Tencent调用。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
静态配置漂移可定位；回滚不会宣称远端已经发放的令牌也回滚。

### Invariants
INV-007：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-013, A-014；定义见 §20。

### Evidence
required test：TEST-A-013, TEST-A-014；required artifact：`evidence/<run_id>/REQ-CONFIG-002/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：新增 env_application_service.py；app/core/security.py；config/runtime/main/部署文档。

## REQ-OAUTH-001 — 不依赖 Portal 的腾讯授权与回调

### Goal
登录后通过本地默认应用发起腾讯用户授权，回到网关即可继续。

### Normative Requirement
- MUST：按 §8.3 与 §9.5生成授权事务；state=24随机字节hex（48字符）、300秒、绑定本地会话/配置/成员；回调仅从固定Tencent token地址换码一次，默认303到网关静态结果页；owner凭会话查询事务状态。 [A-015, A-016]
- MUST NOT：要求Portal部署、调用Backend resolve、接受任意return_to、在回跳URL携带Tencent token或Backend token；重放授权码。 [A-016]

### Inputs
有效本地会话或绑定本地会话的业务token、ENV默认应用、可选return_to。

### Preconditions
PRE-001：应用配置一致；公网HTTPS callback已登记；本地身份尚有效。

### Authoritative State
AuthTransaction为RUNTIME；OAuth返回为OBSERVED；state哈希仅用于匹配。

### State Transition
PENDING→EXCHANGING→RECEIVED/FAILED/OUTCOME_UNKNOWN；错误state不调用Tencent。

### Allowed Side Effects
ALLOW：事务/连接/加密Token行；一次Tencent换码；脱敏日志。

### Forbidden Side Effects
DENY：任何Backend非登录调用；凭URL选择新应用Secret；回调保存密码。

### Ownership Scope
ROW：state事务和owner连接；RESOURCE：本地结果页。

### Idempotency
同state只一次换码；第二次回调STATE_INVALID；成功结果可通过owner查询。

### Failure Semantics
F-001 state过期/应用不匹配→STATE_INVALID；F-002换码超时→OUTCOME_UNKNOWN，重新授权；F-003会话过期→LOGIN_REQUIRED，不换码。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
结果页无敏感字段；授权事务可在原内部系统脚本查询，Portal可完全不运行。

### Invariants
INV-008：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-015, A-016；定义见 §20。

### Evidence
required test：TEST-A-015, TEST-A-016；required artifact：`evidence/<run_id>/REQ-OAUTH-001/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：connection_service.py；callbacks/router.py；api/business.py；新增本地OAuth结果页。

## REQ-OAUTH-002 — 腾讯企业核验与本人连接确认

### Goal
允许.env方式启动而不猜腾讯授权用户的OpenCorpID。

### Normative Requirement
- MUST：非空未知OpenCorpID保存为PENDING_CORP_APPROVAL；只有运维独立核实后更新ENV精确名单且本人user_info验证open_id匹配，才确认ACTIVE；确认生成本人范围授权。 [A-017, A-018]
- MUST NOT：把应用corp_id或内部org_id当OpenCorpID；空列表视为全部允许；管理员代用户确认别人的腾讯身份；仅凭相同姓名绑定。 [A-018]

### Inputs
腾讯换码返回open_id/open_corp_id/scopes；ENV允许表；有效owner会话。

### Preconditions
PRE-001：授权事务完成；Token尚有效；本地owner一致。

### Authoritative State
腾讯身份是OBSERVED；ENV允许表DESIRED；连接状态RUNTIME。

### State Transition
未知公司→PENDING_CORP_APPROVAL；公司获准→PENDING_CONFIRMATION；user_info匹配→ACTIVE；空公司→CORP_REJECTED。

### Allowed Side Effects
ALLOW：连接状态、绑定、owner授权；Tencent user_info读取。

### Forbidden Side Effects
DENY：自动扩展允许列表、跨用户复用现有open_id。

### Ownership Scope
ROW：连接与确认授权；ENTRY：owner绑定。

### Idempotency
同owner/app/open_id确认幂等；不同owner碰撞IDENTITY_CONFLICT。

### Failure Semantics
F-001 公司未批→OAUTH_CORP_APPROVAL_REQUIRED；F-002用户不符→IDENTITY_CONFLICT；F-003授权过期→UPSTREAM_REAUTH_REQUIRED。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
ACTIVE只代表身份与授权可用；读取样本仍需后续内容验收；企业全量不被承诺。

### Invariants
INV-009：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-017, A-018；定义见 §20。

### Evidence
required test：TEST-A-017, TEST-A-018；required artifact：`evidence/<run_id>/REQ-OAUTH-002/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：connection_service.py；env_application_service.py；permission_service.py。

## REQ-OAUTH-003 — 腾讯令牌刷新与后台身份替换

### Goal
腾讯授权可续期，但不触发任何Backend身份查询。

### Normative Requirement
- MUST：刷新使用Tencent refresh_token接口而非Backend；按application/open_id互斥和TokenGeneration CAS更新；临时5xx/网络错误保留旧授权为DEGRADED，明确失效为REAUTH_REQUIRED；后台维护仅在owner本地登录证据有效、未本地阻断且至少存在一个未撤销未过期会话时进行；全部会话注销后停止刷新。 [A-019, A-020]
- MUST NOT：为刷新令牌调用Backend resolve、使用旧Backend refresh_token、并发覆盖新Tencent token、遇403换企业凭据或申请STS。 [A-020]

### Inputs
连接、加密Tencent token、expires、scopes、本地身份有效期。

### Preconditions
PRE-001：公司及owner仍允许；最新TokenGeneration可解密。

### Authoritative State
TokenGeneration为RUNTIME，Tencent expires为OBSERVED。

### State Transition
ACTIVE→刷新成功ACTIVE/暂时故障DEGRADED/明确失效REAUTH_REQUIRED；无有效本地身份则暂停维护。

### Allowed Side Effects
ALLOW：Tencent刷新POST、加密TokenGeneration、审计。

### Forbidden Side Effects
DENY：保存账号密码、定时Backend登录、后台获取员工列表。

### Ownership Scope
ROW：某连接的TokenGeneration。

### Idempotency
同到期窗口多Worker至多1次成功刷新；旧generation禁止覆盖新值。

### Failure Semantics
F-001刷新超时且是否远端轮换未知→DEGRADED并有限重试；再次明确invalid_grant→REAUTH_REQUIRED；F-002提交冲突→保留更高generation，记录冲突，不回写旧token。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
凭据仍仅在网关；刷新不扩大scopes；绝不把上游权限增加当成本地授权增加。

### Invariants
INV-010：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-019, A-020；定义见 §20。

### Evidence
required test：TEST-A-019, TEST-A-020；required artifact：`evidence/<run_id>/REQ-OAUTH-003/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：connection_service.py；maintenance_service.py；TencentClient错误分类；worker。

## REQ-CLIENT-001 — 内部客户端与本地会话令牌交换

### Goal
内部系统仍以独立客户端调用网关，但不要求Backend meeting-context。

### Normative Requirement
- MUST：复用客户端登记与/api/v1/auth/exchange；subject_token只接受本网关已校验Session，输出mt业务token绑定client/owner/session/resource=/api/v1及scope交集；过期不晚于父会话；本轮无refresh/service/agent授予。 [A-021, A-022]
- MUST NOT：把任意外部JWT当subject_token；只传user_id；复用一个全能客户端密钥；忽略客户端限制。 [A-022]

### Inputs
client_id、client_secret、GatewaySession、scopes、resource。

### Preconditions
PRE-001：本地管理员已登记CONFIDENTIAL客户端；调用员工具备本人授权。

### Authoritative State
Client/Session/AccessGrant为授权事实；外部Token无信任来源。

### State Transition
登记→启用；交换→有界子token；父注销/客户端停用→子失效。

### Allowed Side Effects
ALLOW：客户端密钥哈希、子token哈希与审计。

### Forbidden Side Effects
DENY：Backend网络、服务身份模拟员工、下游刷新获取新身份时效。

### Ownership Scope
ROW：Client/AccessToken；FIELD：登录父会话。

### Idempotency
同client多次交换允许新短期token；不延长父session；密钥仅首次响应。

### Failure Semantics
F-001错误client→TOKEN_INVALID；F-002BackendJWT→AUTH_FLOW_REPLACED；F-003scope越界→PERMISSION_DENIED，token新增0。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
内部接口响应保持现有envelope，token不包含TencentSecret或TencentToken。

### Invariants
INV-011：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-021, A-022；定义见 §20。

### Evidence
required test：TEST-A-021, TEST-A-022；required artifact：`evidence/<run_id>/REQ-CLIENT-001/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：auth_service.py；authorization/router.py；api/deps.py；Client/AccessToken迁移；kit exchange_form。

## REQ-QUERY-001 — OAuth 历史会议源查询与结果分页

### Goal
验证已授权用户真实会议数据，不以本地空目录代替腾讯源查询。

### Normative Requirement
- MUST：复用history能力并按§9.6拆90天窗口、逐页20获取；保存QueryResultItem与provider_meeting_id；history写入只证明该用户查询到的来源，不授予参加者录制权限。详情默认读本地；不强制腾讯meeting详情请求。 [A-023, A-024]
- MUST NOT：只取第一页；把空结果当Golden样本成功；用CORP_WINDOW或OAuth仅支持的创建会议详情误当所有历史入口；回填其他owner。 [A-024]

### Inputs
selection=USER_WINDOW、connection_ref、start_at/end_at；owner由会话确定。

### Preconditions
PRE-001：ACTIVE本人OAuth；内部client scope含meeting.read；本地session有效。

### Authoritative State
上游history页OBSERVED；任务结果与完整性RUNTIME；本地目录不是上游全量事实。

### State Transition
PENDING→RUNNING→SUCCEEDED/EMPTY/FAILED；失效会话WAITING_LOGIN。

### Allowed Side Effects
ALLOW：本地Meeting/ResourceOrigin/结果集/检查点；腾讯history GET。

### Forbidden Side Effects
DENY：腾讯会议写操作；跨连接或跨组织合并数据。

### Ownership Scope
ROW：owner连接下Meeting及本作业结果。

### Idempotency
唯一键(connection_id,provider_meeting_id)；同页重复不会多一场。

### Failure Semantics
F-001空中间页/total异常→UPSTREAM_CONTRACT_ERROR；F-002超过上限→RESULT_LIMIT_EXCEEDED；F-003真实空→SUCCEEDED_EMPTY，sample_matched=false。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
工具能按provider ID核对样本，完成分页与count；不需要GET腾讯/v1/meetings/{id}前置通过。

### Invariants
INV-012：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-023, A-024；定义见 §20。

### Evidence
required test：TEST-A-023, TEST-A-024；required artifact：`evidence/<run_id>/REQ-QUERY-001/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：query_service.py；meeting_service.py；新增QueryResultItem与/jobs/{id}/results；schemas/requests.py。

## REQ-QUERY-002 — OAuth 录制发现与精确文件映射

### Goal
可在不知道本地会议UUID时直接获取授权用户录制。

### Normative Requirement
- MUST：新增USER_RECORDINGS时间窗查询；RECORDINGS支持明确provider meeting ID过滤；窗口拆为最多31天、每页20并遍历；指定会议时对返回item.meeting_id再匹配；录制结果携带本地与provider两个ID，来源owner绑定。 [A-025, A-026]
- MUST NOT：无ID时被schema拒绝而无法发现录制；时间窗默认一天掩盖旧样本；将其他meeting的录制并入指定结果；把参加记录当录制权限。 [A-026]

### Inputs
USER_RECORDINGS或RECORDINGS；时间窗默认7天；明确连接。

### Preconditions
PRE-001：本人OAuth允许查询录制；目标sample时间落入查询范围。

### Authoritative State
Tencent record_meetings/record_files为OBSERVED；Recording/Result映射为本地事实。

### State Transition
发现记录→本地METADATA；state处理完成并含record_files→READY录制元数据；无file时保持处理状态。

### Allowed Side Effects
ALLOW：本地会议/录制/资产元数据及结果集；Tencent /v1/records GET。

### Forbidden Side Effects
DENY：/v1/corp/records；索要SecretId/STS；暴露sharing_password/签名URL。

### Ownership Scope
ROW：Recording；identity=(connection_id,record_file_id)。

### Idempotency
同ID重复页不重复记录；会议不符条目不写入本次指定结果。

### Failure Semantics
F-001权限拒绝→UPSTREAM_PERMISSION_DENIED；F-002非目标返回→过滤并记录mismatch计数，唯一已知sample缺失为测试FAIL；F-003分页停滞→失败非完成。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
至少一个获准录制可映射到真实sample；该item可直接用于transcript/minutes接口。

### Invariants
INV-013：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-025, A-026；定义见 §20。

### Evidence
required test：TEST-A-025, TEST-A-026；required artifact：`evidence/<run_id>/REQ-QUERY-002/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：query_service.py::_recordings；schemas/requests.py；meeting_service.py；业务路由。

## REQ-CONTENT-001 — 完整转写读取与版本发布

### Goal
从腾讯读取原生转写，保证本地提取不是一页文本或合成摘要。

### Normative Requirement
- MUST：复用TranscriptCollector并按100段请求分页，处理包含起始pid的边界去重；每页核验会话、owner、connection、lease。检查点加密；完整才发布Asset READY；输出paragraph ID/时间/发言信息及原文，限制完整规范化正文16MiB。 [A-027, A-028]
- MUST NOT：截断后标完整、分页版本混拼、未验证caller提供的record_file_id直接代取、自动ASR/LLM补写。 [A-028]

### Inputs
本地recording_id、有效token、明确已有录制映射；Tencent段落页。

### Preconditions
PRE-001：本地scope meeting.content.read且owner匹配；Tencent实际准入。

### Authoritative State
完整AssetVersion为OBSERVED；checkpoint为RUNTIME非完整正文。

### State Transition
ABSENT→FETCHING→PARTIAL→READY；变更/边界不一致→SOURCE_CHANGED；到期WAITING_LOGIN。

### Allowed Side Effects
ALLOW：腾讯转写GET；加密临时检查点和资产；本地版本/审计。

### Forbidden Side Effects
DENY：STS、企业管理员回退、未完成正文作为READY对外读。

### Ownership Scope
OBJECT/ROW：指定录制transcript版本。

### Idempotency
相同完整hash复用版本；检查点绑定owner+connection+文件+参数；新登录恢复不跨owner。

### Failure Semantics
F-001半途故障保持PARTIAL并重试；F-002超16MiB→PAYLOAD_LIMIT_EXCEEDED；F-003无可证明上游snapshot时consistency=BEST_EFFORT_PAGINATED并校验续接边界，变化重启一次后仍变则失败。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
完整段落count、首末pid、source_page_count、content_hash与导出文件一致。

### Invariants
INV-014：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-027, A-028；定义见 §20。

### Evidence
required test：TEST-A-027, TEST-A-028；required artifact：`evidence/<run_id>/REQ-CONTENT-001/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：content_service.py；mapper.py::TranscriptCollector；storage/local.py；job_service.py。

## REQ-CONTENT-002 — 腾讯智能纪要原文提取

### Goal
得到用户在腾讯侧已生成的纪要，而不是网关再次生成。

### Normative Requirement
- MUST：固定llm=3、text_type=2、lang=default；保存meeting_minute.minute原文与来源参数；todo为空不单独判错；空minute或生成中保留NOT_READY，不写READY。 [A-029, A-030]
- MUST NOT：切换模型得到另一份纪要不告知；用转写自己总结；把没有开启能力与网络故障混为成功。 [A-030]

### Inputs
本地录制ID、Tencent meeting_minute JSON。

### Preconditions
PRE-001：样本在腾讯端相同模型纪要可见且允许访问。

### Authoritative State
Tencent minute原文为业务来源；AssetVersion只读投影。

### State Transition
FETCHING→READY/NOT_READY/BLOCKED；生成期到作业期限为BLOCKED_CONTENT_NOT_READY。

### Allowed Side Effects
ALLOW：纪要GET、本地加密原文及导出。

### Forbidden Side Effects
DENY：LLM调用、翻译、填充todo。

### Ownership Scope
OBJECT/ROW：录制minutes llm=3版本。

### Idempotency
同原文+参数hash保持同版本；生成变化发布新版本。

### Failure Semantics
F-001缺智能能力/生成中→NOT_READY并限定等待；F-002上游403→BLOCKED；F-003结构不符→UPSTREAM_CONTRACT_ERROR。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
Markdown字节与返回minute的UTF-8相同；文件metadata明确非腾讯原生导出下载文件。

### Invariants
INV-015：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-029, A-030；定义见 §20。

### Evidence
required test：TEST-A-029, TEST-A-030；required artifact：`evidence/<run_id>/REQ-CONTENT-002/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：content_service.py；mapper.py::normalize_minutes；kit内容导出。

## REQ-JOB-001 — 本地身份 Worker 与有限重试

### Goal
异步读取不能在后台恢复三个身份接口，也不能无限重试。

### Normative Requirement
- MUST：Worker逐页/发布前校验本地Session、owner和授权；身份失效进入WAITING_LOGIN并释放租约。同owner/client重新登录后显式resume；正常本地节流等待并续租，不计失败；暂时错误退避2/4/8/16/32/60秒上限加0..1秒抖动，最多8次和30分钟总期。 [A-031, A-032]
- MUST NOT：调用backend.resolve/search/context、存密码续会话、把budgeted=false所有错误无限重试、403/配置/错误企业每秒重发。 [A-032]

### Inputs
持久任务、lease_token、deadline_at、progress、localSession、本地权限。

### Preconditions
PRE-001：数据库迁移；任务参数属于本人；单次受理已持久化。

### Authoritative State
Job/租约为RUNTIME；Session截止不可由Worker更改。

### State Transition
RUNNING→WAITING_LOGIN/RETRYING/FAILED/SUCCEEDED；resume只允许WAITING_LOGIN；本地取消CANCELLED。

### Allowed Side Effects
ALLOW：任务/检查点/租约/审计；读取上游；停止过期网络读取。

### Forbidden Side Effects
DENY：无限重试、越权恢复、丢失检查点后假完成。

### Ownership Scope
ROW：作业及租约；OBJECT：检查点。

### Idempotency
领取同作业仅一个有效lease；重复resume不重复作业；同结果只一次发布。

### Failure Semantics
F-001会话过期→WAITING_LOGIN；F-002权限/配置错误→FAILED非重试；F-0038次或30分钟→FAILED/生成中BLOCKED；F-004旧lease写入→LEASE_LOST。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
没运行Worker时作业保持PENDING不误报；重启恢复有状态与审计。

### Invariants
INV-016：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-031, A-032；定义见 §20。

### Evidence
required test：TEST-A-031, TEST-A-032；required artifact：`evidence/<run_id>/REQ-JOB-001/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：worker.py；job_service.py；maintenance_service.py；rate_service.py；本地身份服务。

## REQ-EXPORT-001 — 会议内容落盘与来源标识

### Goal
把“数据提取下来”落实为可核对的文件，而不是仅显示API成功。

### Normative Requirement
- MUST：integration-kit在private/<run_id>/按connection/录制UUID输出会议与录制JSON、完整transcript.json、transcript.txt、minutes.md和manifest.json；JSON/TXT是网关规范化导出，Markdown为已返回minute原文；manifest含provider/local ID、页数、字节数、摘要。 [A-033, A-034]
- MUST NOT：把生成的JSON/TXT称为腾讯原生文件下载；用会议主题作为路径；覆盖异内容文件；把会议正文放公共evidence。 [A-034]

### Inputs
已完成任务与完整API数据；指定私有根目录。

### Preconditions
PRE-001：owner/read权限有效；合法无symlink目标目录；版本一致。

### Authoritative State
AssetVersion为源；私有export manifest是文件来源证据。

### State Transition
TEMP_WRITTEN→校验摘要→原子rename→COMMITTED；失败保持未提交目标。

### Allowed Side Effects
ALLOW：限定private根目录文件、脱敏文件摘要回执。

### Forbidden Side Effects
DENY：任意路径写、符号链接跳出、token/密码写入导出manifest、未经授权音视频下载。

### Ownership Scope
FILE/GENERATED_ONLY：本run导出；USER_OWNED：其他文件不动。

### Idempotency
相同目标相同字节no-op；相同路径异字节EXPORT_CONFLICT。

### Failure Semantics
F-001磁盘不足→目标不存在且临时文件可清理；F-002摘要不符→EXPORT_INTEGRITY_FAILED；F-003写出目录→PATH_NOT_ALLOWED，0外部写。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
本轮核心提取PASS需要至少一个非空转写和非空纪要文件及可验证manifest。

### Invariants
INV-017：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-033, A-034；定义见 §20。

### Evidence
required test：TEST-A-033, TEST-A-034；required artifact：`evidence/<run_id>/REQ-EXPORT-001/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：integration-kit/tools/read_content.py；新增manifest导出模块；templates/golden-consumer。

## REQ-MIGRATE-001 — 旧身份、应用与授权迁移

### Goal
隔离旧Backend member_id与本地账号身份，避免无证据接管历史数据。

### Normative Requirement
- MUST：升级增加本地表/身份来源及ENV所有者字段；默认保留旧业务行、冻结旧身份Token/作业、关闭旧入口；首次真实登录后使用单独的受审映射清单显式迁移有owner证据的OAuth连接。新空数据库可直接采用本模式。 [A-035, A-036]
- MUST NOT：自动按姓名/邮箱匹配、全表member_id=user.id、移除数据库卷、复用身份来源不明的Token、反向调用旧接口补迁移。 [A-036]

### Inputs
旧DB备份、旧源SHA、新迁移版本、显式old_member_id→backend_user_id/org的审计映射。

### Preconditions
PRE-001：进入维护窗口；旧API/Worker停止写；备份校验完成。

### Authoritative State
旧数据归属保留；新LocalMember由真实登录创建；映射清单USER_OWNED。

### State Transition
LEGACY_ACTIVE→LEGACY_SUSPENDED；确认映射→ACCOUNT_LOGIN归属；无法证明→LEGACY_UNMAPPED保持不可读。

### Allowed Side Effects
ALLOW：迁移新增表/标记；受审连接owner更新；令牌废止；恢复资料。

### Forbidden Side Effects
DENY：无所有权证明删除/接管；恢复旧镜像后自动启用禁止接口。

### Ownership Scope
ROW/迁移明细清单：仅显式允许行；其他USER_OWNED。

### Idempotency
重跑同迁移幂等；映射清单digest变更必须重新审核。

### Failure Semantics
F-001归属冲突→IDENTITY_MIGRATION_REQUIRED；F-002事务失败→映射受管范围=T0；F-003回滚失败→ROLLBACK_FAILED，保留备份，停服务。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
旧token不能访问新模式；新空部署不要求旧Backend服务凭据；旧资源不会被丢弃。

### Invariants
INV-018：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-035, A-036；定义见 §20。

### Evidence
required test：TEST-A-035, TEST-A-036；required artifact：`evidence/<run_id>/REQ-MIGRATE-001/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：alembic迁移（命令生成revision）；models；auth/worker；新增migration-check CLI。

## REQ-DEPLOY-001 — 指定服务器部署与就绪检查

### Goal
无需整套nodeskclaw及Portal，只依赖唯一登录服务和腾讯OAuth。

### Normative Requirement
- MUST：提供基于现有锁文件的冻结构建、数据库迁移→env-apply→API/Worker顺序；健康检查不访问Backend；检查实际API/Worker出口、TLS callback、私有卷/密钥持久化；保留/data/projects指定目录。 [A-037, A-038]
- MUST NOT：关闭鉴权跑通、把HTTP私网当TLS、默认占用9999端口或覆盖原业务、以重建密钥修复启动、把Backend health列为readiness前置。 [A-038]

### Inputs
批准的部署SHA、ENV、现有端口/网络/卷、唯一登录地址。

### Preconditions
PRE-001：私有配置权限；无未核对端口冲突；新发布已通过离线契约测试。

### Authoritative State
ENV/镜像digest/迁移head为部署事实；实际登录和腾讯请求为外部观察。

### State Transition
DEPLOYED→LOCAL_READY→LOGIN_VERIFIED→OAUTH_VERIFIED→DATA_VERIFIED分别记录。

### Allowed Side Effects
ALLOW：专属容器/网络/DB迁移/私有卷/Nginx受管location；外部只读连通探测无凭据。

### Forbidden Side Effects
DENY：系统级全局代理改写、开放数据库公网、后台未经批准创建真实会议。

### Ownership Scope
FILE/SECTION：本项目配置；RESOURCE：专属服务。

### Idempotency
重启持久数据不丢；迁移/env-apply重复无额外权限；不自动git reset。

### Failure Semantics
F-001配置/DB错→ready503；F-002Backend暂不可达→登录503，不伪造身份；F-003API/Worker配置代次不一致→CONFIG_DRIFT。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
本地ready成功不表示Tencent可读；报告必须有白名单实际出口与HTTPS回调证据。

### Invariants
INV-019：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-037, A-038；定义见 §20。

### Evidence
required test：TEST-A-037, TEST-A-038；required artifact：`evidence/<run_id>/REQ-DEPLOY-001/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：Dockerfile；deploy/compose.yaml；nginx示例；app/cli.py/main.py；部署手册。

## REQ-CMD-001 — OAuth 单通道联调工具

### Goal
工具不再要求先配置AK/SK、STS或旧Backend专用令牌。

### Normative Requirement
- MUST：更新kit契约版本并提供login→client exchange→oauth start/status/confirm→history/records→content/export→report的真实调用脚本；密码交互或0600文件读入不回显；独立run目录；只读自动化不能开启写测试。 [A-039, A-040]
- MUST NOT：继续调用三个旧端点、只读取本地缓存就声称腾讯已调用、占位skip/NOT_RUN退出0、复用其他run的PASS、把提供的真实JWT写fixture。 [A-040]

### Inputs
gateway HTTPS base、账号、交互密码、ENV默认应用、本轮sample provider IDs、运行SHA。

### Preconditions
PRE-001：§9.5新API已实现；现场绑定文件明确实际SHA及非敏感sample。

### Authoritative State
服务器API响应/上游计数/文件manifest是Evidence；脚本文案不是证据。

### State Transition
PREFLIGHT→LOGIN→OAUTH→QUERY→CONTENT→EXPORT→REPORT；阻断阶段保留明确原因。

### Allowed Side Effects
ALLOW：网关本地登录/授权/读取副作用；private文件和脱敏evidence。

### Forbidden Side Effects
DENY：直接脚本绕网关请求腾讯拿数据、修改报告判定条件、自动提交密钥。

### Ownership Scope
FILE：kit tools、模板、当前run输出；目标服务器项目目录不重命名。

### Idempotency
重复只读执行新run；重复同run验收不采纳过期token和旧结果。

### Failure Semantics
F-001接口不匹配→KIT_CONTRACT_MISMATCH；F-002session到期暂停并要求再登录；F-003样本未命中/内容为空→非零报告结果。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
工具生成本次OAuth数据提取报告，AKSK/STS为NOT_APPLICABLE且不阻断本轮OAuth主gate。

### Invariants
INV-020：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-039, A-040, A-041；定义见 §20。

### Evidence
required test：TEST-A-039, TEST-A-040, TEST-A-041；required artifact：`evidence/<run_id>/REQ-CMD-001/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：/data/projects/meeting-integration-kit/tools及session.sh/manual-checks模板；repo scripts/tencent_live_smoke.py；tests/live。

## REQ-SEC-001 — 凭据、路径与数据隔离

### Goal
使用单一登录接口不减弱本地鉴权或扩大会议数据暴露。

### Normative Requirement
- MUST：执行§18所有威胁控制：固定地址、禁止重定向/代理、私有HTTP风险显式、敏感字段屏蔽、加密OAuth token与正文、owner逐请求校验、文件路径约束、登录限流与业务只读操作白名单。 [A-042, A-043]
- MUST NOT：日志打印登录响应/密码/Secret/TencentToken/auth_code/state/签名URL；JSON响应信任前端角色；将会议正文当指令执行；把媒体下载视为本轮默认动作。 [A-043]

### Inputs
所有路由、外部响应、导出路径、日志参数、限流计数。

### Preconditions
PRE-001：安全策略由集中模块执行，不由提示词决定。

### Authoritative State
网络允许列表/ACL/文件根是安全边界；日志与导出是受管资源。

### State Transition
非法输入→DENY并安全错误；流内发生撤权→停止后续可控制I/O，不声称追回已发字节。

### Allowed Side Effects
ALLOW：安全计数和脱敏审计；必要阻断状态。

### Forbidden Side Effects
DENY：秘密输出、任意网络/路径、扩大权限的自动修复。

### Ownership Scope
FILE/ROW/RESOURCE：按请求owner和运行输出根约束。

### Idempotency
重复恶意请求不得产生额外授权；登录失败5次/账号摘要/5分钟锁10分钟，且每来源IP最多30次/分钟。

### Failure Semantics
F-001日志写失败时带正文的业务操作不降级写明文；F-002权限撤销→拒绝新访问；F-003风险HTTP未显式批准→CONFIG_INVALID。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
使用假凭据标记的测试扫描所有输出=0敏感值；公网入口不泄露第三方凭据。

### Invariants
INV-021：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-042, A-043；定义见 §20。

### Evidence
required test：TEST-A-042, TEST-A-043；required artifact：`evidence/<run_id>/REQ-SEC-001/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：core/security/middleware/errors；存储/日志；本地身份/网络策略；kit。

## REQ-EVID-001 — 工程模板追踪与 OAuth 读取验收门禁

### Goal
用真实可验证证据证明单通道数据提取完成。

### Normative Requirement
- MUST：执行§20—§30的输入、负向、故障、Evidence和Release Gate；每次证据关联源SHA、运行绑定、工具版本、不可变文件摘要与Oracle。主gate要求实际登录、OAuth身份、目标录制、完整转写和纪要导出以及禁止端点计数0。 [A-044, A-045]
- MUST NOT：仅写PASS标签、引用旧CI代替变更测试、把BLOCKED/SKIPPED/空样本/未调用上游当通过；未经审批将PRD改APPROVED_FOR_PLAN。 [A-045]

### Inputs
本次test/trace/manifest/安全计数与人工现场证据。

### Preconditions
PRE-001：定义的必需AC均有测试和输出路径；不同run独立。

### Authoritative State
Evidence为EVIDENCE_STATE；不是业务权限来源。

### State Transition
每AC计划→执行PASS/FAIL/BLOCKED/SKIPPED；Required非PASS→release FAIL并非零退出。

### Allowed Side Effects
ALLOW：限定evidence目录与报告文件；不更新业务源。

### Forbidden Side Effects
DENY：修改测试标记伪PASS、输出真实凭据、覆盖用户输入/旧证据。

### Ownership Scope
GENERATED_ONLY：本run报告/manifest；USER_OWNED：真实样本说明。

### Idempotency
输入证据相同输出摘要相同；证据缺失/篡改拒绝。

### Failure Semantics
F-001缺证据→EVIDENCE_INCOMPLETE；F-002摘要不符→EVIDENCE_TAMPERED；F-003无真实sample→BLOCKED非零。 业务事务按 §14；已经发生的登录/腾讯换码不是可回滚本地副作用。

### Postconditions
分别报告结构校验/离线测试/现场OAuth gate；PRD发布时只能声明文档检查，不声明业务通过。

### Invariants
INV-022：目标范围、身份、结果不得超出本需求合同；任何失败不通过替换凭据、owner或上游接口继续执行。相同受管输入重复执行遵守上述Idempotency。

### Error Codes
本需求 Failure Semantics 列出的 reason，及 §9.7 共同认证/配置错误；错误不会原样回显上游敏感消息。

### Acceptance
A-044, A-045, A-046；定义见 §20。

### Evidence
required test：TEST-A-044, TEST-A-045, TEST-A-046；required artifact：`evidence/<run_id>/REQ-EVID-001/receipt.json` 与对应测试结果；required digest：§13 文件 SHA256；required runtime output：命令退出码、结构化reason、允许/禁止网络计数和Oracle expected/actual。
代码范围：kit report.py；tests/live；CI；contracts及本PRD审阅记录。

# 11. Side-Effect Contract

| Operation | DB Write | File Write | Network | Cache | User Data | Business Source |
|---|---:|---:|---|---:|---|---|
| 配置 check | NO | 仅指定脱敏回执 | NO | NO | NO | NO |
| migration dry-run | NO | 指定计划/摘要 | 只连接本地PostgreSQL读取schema | NO | NO | NO |
| migration / env-apply | 受管行 | 恢复包/回执 | 本地PostgreSQL | 配置版本 | 不改未知owner数据 | 不访问腾讯 |
| account-login | 本地身份/会话/失败计数 | 脱敏日志 | 唯一Backend登录POST | 短期身份快照 | 上游可能更新last_login_at | Backend登录审计不可本地回滚 |
| 本地会话查询/注销 | 查询NO，注销YES | 脱敏审计 | 无外部HTTP | 本地会话 | 仅当前会话 | NO |
| OAuth start | state事务 | 脱敏审计 | 返回授权URL；浏览器访问腾讯 | 事务状态 | 用户主动授权 | Tencent授权关系可能改变 |
| OAuth callback/confirm/refresh | 加密Token/连接 | 脱敏审计 | Tencent换码/user_info/refresh | Token | 该owner连接 | OAuth凭证轮换，不修改会议 |
| 内部客户端登记/交换 | Client/Token哈希 | 仅首次私有凭据交付/审计 | 无BackendHTTP | 本地授权 | 当前用户/client | NO |
| history/records/content query | 元数据、进度、正文版本 | 私有密文/检查点 | Tencent白名单GET | 本地内容 | 获准会议 | NO |
| 本地列表/分页读取 | 审计 | 脱敏日志 | 仅需上游来源复核时白名单GET | 私有cache | 授权正文 | NO |
| kit export | NO（网关读审计除外） | private当前run | 网关REST | 本地文件 | 已授权内容副本 | NO |
| report | NO | evidence/report | NO | NO | 不含正文 | NO |
| 创建/修改/STS/企业全量/旧身份接口 | NO | 仅拒绝审计 | 禁止，计数0 | NO | NO | NO |

缓存、审计、配置投影都是副作用。“只读测试”仅指不修改腾讯会议业务资源，不意味着服务器0写入。工具只读参数与 write guard 使用动作集合，不以 HTTP GET/POST 区分授权操作：Backend登录、OAuth换码和本地作业POST均为本任务允许动作。

# 12. Ownership Contract

## 12.1 Ownership Type

ENV配置文件为 USER_OWNED；受管应用字段为 FIELD/ENV_MANAGED；本地成员、会话、连接、Job为ROW；正文为OBJECT；导出与回执为FILE/GENERATED_ONLY；Nginx只允许新增或修改预先标记的SECTION。会议主题、原始正文永不成为路径或命令。

## 12.2 Ownership Rule

创建时：默认OAuth应用由 `managed_key=tencent-default` 和当前org所有；用户连接归属真实本地Member。更新时：只有对应writer可改其字段；管理API不能覆盖ENV字段。运维修改 `.env` 后，先校验和env-apply，再重建API/Worker载入同代次。

用户修改生成文件后：摘要不同则 PRESERVE + REPORT，不覆盖。升级：不修改与本次变更无关的旧应用、ACL、Nginx段。remove：逻辑停用受管资源；没有所有权证明的旧记录、私有卷、证据、密钥保留。正文到期删除限定为DB明确标记的object_key。

## 12.3 Drift

受管数据库字段或进程配置与LAST_APPLIED不一致：CONFIG_DRIFT，BLOCK受影响Tencent请求；就绪输出503。非受管文件漂移：PRESERVE。ENV合法同identity变更通过明确apply覆盖受管投影；没有FORCE旁路。身份源URL/org/corp/app变化不能用同一次Secret更新处理。

# 13. Hash / Identity Contract

H-01：业务身份唯一键为 `(identity_source_id, internal_org_id, backend_user_id)`。`identity_source_id`由部署端固定规范化Backend登录URL的SHA256确定，不能从账号昵称生成。URL规范化规则：scheme/host小写，显式保留4510，path精确`/api/v1/auth/account-login`，禁止query/fragment/userinfo；只接受本release固定地址。

H-02：GatewayMemberID、Application UUID、Connection UUID由服务端随机UUIDv4生成；与BackendUserID/OpenID/会议号完全分开。Tencent外部ID按收到的十进制字符串保存；数字型record_file_id先无损转换为字符串，不能经JavaScript浮点数中转。

H-03：Session/业务Token/state：32字节安全随机令牌（state按REQ-OAUTH-001为24字节hex），只在数据库保存UTF-8原始token的SHA256十六进制摘要；日志/evidence不含token/state或其可关联摘要。JWT解码字段不参与身份认证。

H-04：Canonical JSON=`json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')`。数组按业务原顺序；权限集合等无序集合先字典序排序；时间先转UTC标准ISO8601。字符串不做Unicode等价归一化，不trim会议正文。

H-05：配置identity digest包含：规范化登录URL、org_id、managed_key、tencent_corp_id、sdk_id。非秘密配置与Secret整体版本用`HMAC-SHA256(K_config,CanonicalJSON(config))`，K_config为现有密钥环派生专用key。仅内部DB保存该HMAC，不把Secret或普通Secret摘要写报告；报告只列generation与字段名。

H-06：正文content_hash=`SHA256(CanonicalJSON({provider:'tencent_meeting',application_id,connection_id,provider_meeting_id,provider_record_file_id,kind,source_parameters,normalized_content}))`。包含原文、pid、发言者/时间字段及模型/类型；不含fetched_at、任务ID、临时URL、token。来源不同不可因正文相同跨owner共享授权缓存。

H-07：检查点摘要含查询窗口、连接、provider文件ID、kind、最后pid、已保存段落hash和页号。上游无snapshot时，校验续接边界不等于能证明整个会议同一时刻快照，标记 `BEST_EFFORT_PAGINATED`。

H-08：单文件证据=`SHA256(file_bytes)`。目录清单摘要=`SHA256(按UTF-8相对POSIX路径排序后拼接(relative_path + NUL + file_sha256_hex + LF))`。禁止absolute/path traversal/symlink；文件时间、所有者等metadata不参与内容摘要，但单独记录mode。源码、模板和工具文件使用字节摘要；未提交代码还记录tree digest与dirty状态。

# 14. Transaction Contract

## 14.1 Transaction Boundary

| 事务 | TXN includes | TXN excludes | T0 / 失败行为 |
|---|---|---|---|
| TX-LOGIN | 本地Member+Snapshot+Session+安全审计 | HTTP登录、密码内存、Backend last_login_at | 本地提交失败不签发；上游已发生登录不回滚 |
| TX-ENV | Application受管字段+凭据版本+Projection代次 | `.env`、镜像、Tencent Token生成 | 失败恢复受管字段/代次为T0；外部配置文件仍需运维处理 |
| TX-OAUTH-CLAIM | 验证并消费state标记EXCHANGING | Tencent换码网络 | claim后换码超时不能回滚为PENDING重放 |
| TX-OAUTH-STORE | Connection/TokenGeneration/事务结果 | 腾讯新令牌产生 | 保存失败不发布ACTIVE；记录需重新授权/受控重试的失败事实 |
| TX-CONFIRM | 连接确认+owner绑定+owner限定ACL+审计 | user_info网络 | user_info先完成；事务内再校验本地身份/配置/Token代次；失败无部分授权 |
| TX-REFRESH | CAS凭据版本/状态 | Tencent刷新网络 | 旧generation不能覆盖新；远端轮换已发生时不承诺旧Token可恢复 |
| TX-PAGE | 一页元数据/结果集+下一页checkpoint+租约fence | Tencent页网络 | 失败该页不发布checkpoint；旧页保留，按页恢复 |
| TX-CONTENT | AssetVersion READY+object_key+hash+审计 | 写暂存密文、Tencent网络 | 文件先落私有temp并校验；事务发布成功前不可读READY |
| TX-MIGRATE | 显式owner映射与停用标记 | 备份、上游状态 | 失败只回滚受管行；不删未知资源 |

## 14.2 Commit Order

通用：验证输入/本地权限 → 获取锁/租约 → 读取T0 → 上游读取（不长持数据库事务）→ 再验证owner/Session/config generation → 原子写受管状态 → 发布结果 → 写证据。

特殊OAuth换码：先消费state，再出网，再入库；这是防止重放的明确例外，不回滚state到可用。授权确认/刷新必须再次核验本地快照，否则登录过期可能在网络请求后变成越权发布。

## 14.3 Failure Atomicity

T0为首次本地受管mutation前的行/字段快照。数据库事务失败时，业务可见的受管scope等于T0；脱敏失败审计追加属于单独允许副作用，不计入业务回滚相等比较。内容临时密文孤儿不对外暴露，记录到清理队列，24小时后仅清理未引用对象。

导出：private staging写入 → fsync → 摘要校验 → 同文件系统原子rename。任何一步失败不生成complete=true最终manifest。已经发到客户端的响应字节和上游Token轮换无法回滚；报告列为不可逆外部事实。

## 14.4 Rollback Failure

错误 `ROLLBACK_FAILED`；暂停受影响API写入与Worker；恢复包记录原版本、受管键、备份摘要及失败阶段，真实秘密仅留加密备份。保留所有恢复资料，至少30天且直到管理员人工验收恢复为止；仅到期但未恢复时不能删除。恢复完成后复核受管摘要与访问权限，再重启。旧版本仍可能调用被禁止接口，所以本模式回滚不能自动解除网络阻断。

# 15. Conflict Contract

| Conflict | Detection | Default Behavior | Error | Mutation |
|---|---|---|---|---|
| 同ENV默认应用已有非ENV所有者 | managed_key/sdk/org与ownership对比 | BLOCK/PRESERVE | CONFIG_CONFLICT | 受管应用0 |
| app/corp/org/身份源变化 | identity_digest不同 | BLOCK；新部署或显式迁移 | CONFIG_CONFLICT | 原Token/owner 0 |
| 同用户并发首次登录 | 活跃唯一键 | 锁/唯一冲突后读取已有Member | 不返回假账号 | Member至多1 |
| 同open_id不同本地owner | app/open_id唯一键 | BLOCK | IDENTITY_CONFLICT | 原绑定0 |
| 两Worker刷新 | 锁+generation CAS | 新代次优先，旧提交拒绝 | TOKEN_VERSION_CONFLICT | 无降代 |
| 旧member_id没有映射证据 | 映射清单缺口 | PRESERVE + BLOCK | IDENTITY_MIGRATION_REQUIRED | 原数据0 |
| 导出相同路径不同字节 | file hash比较 | PRESERVE + BLOCK | EXPORT_CONFLICT | 既有文件0 |
| 生成配置已被人工修改 | last_applied比较 | PRESERVE + REPORT | CONFIG_DRIFT | 未经apply不覆盖 |
| 读请求包含他人的connection/recording | 当前owner比较 | DENY | RESOURCE_NOT_ACCESSIBLE | 正文0 |

# 16. Compatibility / Migration

## 16.1 Existing State

当前基线固定SHA，原身份源是Backend三接口，member_id指原OrgMembership身份；原腾讯应用来自管理API，存在AKSK/OAuth混合数据和后台采集作业。旧业务token、Portal入口、integration-kit subject_token均可能依赖Backend JWT。本轮不假设已部署服务器与GitHub完全一致；运行前核对HEAD与dirty摘要。

## 16.2 Migration

1. `detect`：只读扫描schema/version、旧token、旧连接owner、ENV冲突、排队job；输出迁移摘要，不打印凭据。
2. `preserve`：备份DB、私有卷和密钥，记录旧运行SHA；停止旧Worker；禁止旧身份出站规则继续生效。
3. `migrate`：添加本地身份/会话/config ownership/结果表、索引和来源字段；迁移通过Alembic命令生成并审核。
4. `adopt`：首次真实登录得到新LocalMember。只有显式owner映射有证据时才接管原OAuth Connection；无证据的记录标LEGACY_UNMAPPED，数据保留不可读。需要迁移连接时，腾讯用户重新授权/确认后才启用。
5. `apply`：ENV同步默认应用，若冲突返回报告；不静默覆盖旧管理API应用。新空测试库无需旧映射，可直接初始化。
6. `switch`：新mode使用本地会话；旧JWT exchange/Portal返回AUTH_FLOW_REPLACED。更新kit配置和令牌文件名，删除旧凭据前由运维备份确认。
7. `verify`：全流程出站审计，三个禁止接口0；运行新的OAuth数据提取门禁。

## 16.3 Unknown Ownership

未知资源、未知配置段、未知旧member_id一律保留并报告。不能以清空数据库、down -v、git reset --hard、自动替换org_id作为迁移手段。

## 16.4 重试和等待的固定规则

正常节流不算错误；HTTP429按可信Retry-After等待（上限300秒），仍受任务30分钟总期限。临时网络/HTTP5xx有限退避；永久权限、错误配置、公司不匹配不重试。生成中每30秒一次，任务总期内等待，超时返回BLOCKED_CONTENT_NOT_READY；不归零失败次数形成无限循环。WAITING_LOGIN单独暂停，不继续网络轮询；超过24小时不恢复则CANCELLED并保留元数据、清理未引用临时检查点。

# 17. External Dependency Contract

## 17.1 源码与输入

| name | immutable identity | required | fallback/offline/failure |
|---|---|---|---|
| meeting-gateway | `79e22d08b623a4f7816db05af631a463fe14348b` | Runtime/Auth/Connection/Query及现有模型 | 本PRD只描述该基线；实施HEAD变化先生成差异清单，不自动降级 |
| 模板 | §17.4文件SHA256 | 第0—36章及需求/验收格式 | 模板输入缺失时文档生成BLOCKED |
| Backend登录接口 | 用户指定URL；部署版本未提供 | POST account-login，JSON `{account,password}` | 不调用替代接口；离线仅测试合成fixture，不能代替登录 |
| integration-kit | 部署时记录tree SHA256；用户已上传包SHA256见§17.4 | 替换登录、exchange、single-channel报告 | 旧工具不自动适配身份；不满足新合同则KIT_CONTRACT_MISMATCH |
| Tencent OAuth与数据API | 官方云服务，无可固定内部提交；记录核验日期2026-10-17 | 下表 | 不切AKSK；接口未支持返回能力错误，合成fixture不可宣称真实通过 |

## 17.2 Backend 唯一出站白名单

```text
method = POST
scheme = http（当前用户指定；需显式HTTP例外）
host = 192.168.102.247
port = 4510
path = /api/v1/auth/account-login
query = empty
redirect = forbidden
proxy inheritance = disabled
```

不向该Backend发GET健康探测，不请求三接口或其他目录/令牌接口。开发阶段允许人工核对已经提供的Schema源代码；运行时不会fetch该源码或部署文档补鉴权。

## 17.3 Tencent 允许的上游操作与资料边界

| 能力 | 方法/路径 | 本轮范围与来源 |
|---|---|---|
| 用户授权页面 | 浏览器GET `meeting.tencent.com/marketplace/authorize.html` | 参数corp_id/sdk_id/redirect_uri/state；需用户同意 [WEB-01] |
| 换码/刷新/凭证核验 | POST `meeting.tencent.com/wemeet-webapi/v2/oauth2/oauth/{access_token,refresh_token,user_info}` | 仅这三个精确枚举；凭据独立于Backend [WEB-01] |
| 历史会议 | GET `api.meeting.qq.com/v1/history/meetings/{open_id}` | OAuth支持；用户创建与参加过的历史记录；90天窗口 [WEB-02] |
| 用户录制 | GET `api.meeting.qq.com/v1/records` | OAuth；录制权限由腾讯校验，31天窗口 [WEB-03] |
| 录制详情 | GET `api.meeting.qq.com/v1/addresses/{record_file_id}` | 仅有权限的OAuth录制；不要求STS [WEB-04] |
| 转写 | GET `api.meeting.qq.com/v1/records/transcripts/details` | OAuth支持；operator_id=open_id/type=2；不要求STS [WEB-05] |
| 智能纪要 | GET `api.meeting.qq.com/v1/smart/minutes/{record_file_id}` | OAuth；指定模型和相关智能功能/内容已生成 [WEB-06] |
| 待开始/指定会议详情 | GET `/v1/meetings`、`/v1/meetings/{id}` | 官方说明OAuth范围与OAuth创建来源有关，不作为已有会议结果必经路径 [WEB-07] |
| 企业全量 | `/v1/corp/records`、`/v1/corp/meetings` | 不属于本轮OAuth读取合同，禁止fallback [WEB-08] |

官方录制文档的描述段强调创建者，参数段又列出超级管理员/录制管理角色；本PRD不扩大解释为“所有参加过的会议均可下载”。Golden样本固定为测试授权人本人创建且腾讯端内容可见，并以真实接口返回核实。[WEB-03] 录制详情文档另有OAuth应用范围说明，不能仅凭客户端可见就保证第三方应用可读取。[WEB-04]

## 17.4 资料与来源清单

USR-01：用户本轮提供的account-login成功响应（Token未纳入文档）；只证实该样例字段，不证实全部账号与当前部署实时状态。

USR-02：用户提供的目录、截图、OAuth应用/出口/回调信息；需要现场网络验证。

SRC-01：仓库master分支读取记录，固定SHA见元数据。

SRC-02：`https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/runtime.py`；读取基线为固定SHA，引用符号见§3。

SRC-03：`https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/integrations/nodeskclaw_backend/client.py`；读取基线为固定SHA，引用符号见§3。

SRC-04：`https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/services/auth_service.py`；读取基线为固定SHA，引用符号见§3。

SRC-05：`https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/core/config.py`；读取基线为固定SHA，引用符号见§3。

SRC-06：`https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/services/connection_service.py`；读取基线为固定SHA，引用符号见§3。

SRC-07：`https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/services/query_service.py`；读取基线为固定SHA，引用符号见§3。

SRC-08：`https://github.com/loudon84/nodeskclaw/blob/83edfb0d97f07920deb8bb9ce44a91e3e32cc3af/nodeskclaw-backend/app/schemas/auth.py`。用于确认历史AccountLoginRequest字段；不是私网部署版本证明。该Schema的UserInfo还有must_change_password序列化行为，网关不能据此声称能看见Backend未返回的状态。

WEB-01：腾讯第三方应用鉴权：`https://cloud.tencent.com/document/product/1095/51257`；官方授权流程辅助说明：`https://cloud.tencent.com/document/product/1095/85377`。

WEB-02：历史会议：`https://cloud.tencent.cn/document/product/1095/53805`。

WEB-03：录制列表：`https://cloud.tencent.com/document/product/1095/51189`。

WEB-04：录制详情：`https://cloud.tencent.cn/document/product/1095/51180`。

WEB-05：转写详情：`https://cloud.tencent.com/document/api/1095/65111`。

WEB-06：智能纪要：`https://cloud.tencent.com.cn/document/product/1095/109458`。

WEB-07：OAuth会议范围：`https://cloud.tencent.com/document/product/1095/42421`；`https://cloud.tencent.com/document/product/1095/93432`。

WEB-08：账户级录制：`https://cloud.tencent.com/document/product/1095/53224`。

官方资料仅用于上述能力、字段与限制核验；本地Session、ENV模式、暂停规则、ACL和导出都是本PRD设计决策，不声称腾讯官方要求。全部线上资料核验日期为2026-10-17。

输入文件：`需求PRD工程模板.md`；SHA256=`b00234e6d103b2c102cbcc7b02fbcd961e71b0ce784ee736ead592c301e35eff`。

输入文件：`meeting-gateway-integration-kit-20261017.zip`；SHA256=`cf8e70bbf201562724a6132a5e06ea4d7d96361acad71b0463691523168400ca`。

# 18. Security Contract

| Threat | Control | Acceptance |
|---|---|---|
| 使用被公开Token或伪造user数据 | 密码经固定登录通道；丢弃上游Token；新本地会话；不将样例凭据写fixture | REQ-AUTH-001 / REQ-SEC-001 对应正负验收 |
| HTTP私网登录被监听/篡改 | 精确目标、显式HTTP例外、仅受控网络/隧道、禁止日志和抓包保存请求体；记录传输不加密风险 | REQ-BOUNDARY-001 / REQ-DEPLOY-001 |
| 任意登录/SSRF/重定向 | URL固定且集中允许列表；不继承代理；禁止第二跳；失败无fallback | REQ-BOUNDARY-001 |
| 无限猜密码 | 账号HMAC计数与可信来源IP限流；错误统一；禁止日志记录账号密码对 | REQ-SEC-001 |
| Backend停用不能实时获取 | 900秒本地快照上界、过期停任务、管理员本地block；不冒称实时失效 | REQ-AUTH-002 |
| 管理角色误用 | ENV管理员名单且portal_org_role条件；管理不等于他人正文访问 | REQ-ACL-001 |
| OAuth CSRF/账号错绑 | 一次性state绑定本地会话/应用/代次，user_info精确核对，owner确认 | REQ-OAUTH-001 / 002 |
| 令牌泄露/刷新竞态 | 私有加密存储、generation CAS、运行时摘要不输出；Backend与Tencent凭据域分离 | REQ-CONFIG-002 / REQ-OAUTH-003 |
| 跨用户/跨应用数据泄漏 | 所有列表/结果/正文/导出基于owner与client，缓存不绕权 | REQ-ACL-001 / REQ-CLIENT-001 |
| 路径穿越/软链接 | 真实根目录、拒绝..及symlink、UUID命名、独占创建、原子rename | REQ-EXPORT-001 |
| 会议正文提示注入/任意执行 | 正文只存储/传输；不触发shell/LLM/MCP，工具只执行固定操作 | REQ-SEC-001 |
| 依赖来源漂移 | 实际源码SHA、uv.lock、镜像摘要和kit摘要记录；版本不符不静默跳过 | REQ-DEPLOY-001 / REQ-CMD-001 |
| 日志泄密 | endpoint标签而非带query完整URL；body/header不记录；换码callback日志脱敏/禁用查询串 | REQ-SEC-001 |

明文HTTP只作为用户指定端点的受限部署事实，不对其他主机启用HTTP、不关闭Tencent HTTPS证书验证。日志收集器不得导出`.env`、Token文件或包含登录请求体的抓包。

# 19. Observability

阶段固定为 `PREFLIGHT → CONFIG_APPLY → LOGIN → OAUTH_AUTHORIZE → OAUTH_CONFIRM → QUERY → FETCH → EXPORT → VERIFY → REPORT`。

每条安全回执包括：run_id、operation_id、stage、status、UTC时间、source_sha、image_digest（部署阶段）、resource别名/本地ID、reason、trace_id、耗时、网络分类计数。不会保存密码、Secret、上游Token、state、auth_code、带签名URL。必要provider原始ID存private binding，报告使用摘要或批准的测试别名。

计数器至少分 `backend.account_login`、`backend.forbidden_attempt`、`backend.forbidden_sent`、`tencent.oauth_exchange`、`tencent.oauth_refresh`、`tencent.user_info`、`tencent.history`、`tencent.records`、`tencent.transcript`、`tencent.minutes`、`tencent.business_write`。禁止发送数与业务写发送数为0；负向测试的forbidden_attempt可以大于0。

readiness输出只表达本进程、数据库、迁移head和配置代次一致性，`backend_login_observation`可展示最后一次实际登录结果/时间，但不主动发请求。`LOCAL_READY`与`DATA_VERIFIED`分别展示，不复用一个绿色灯表示全链路通过。

# 20. Acceptance Design Standard

验收的 Given/When/Then 按本节执行；测试记录 facts，由Oracle比较facts与独立fixture/Golden绑定。`expected_from` 只能引用测试准备阶段固定的fixture或经人工批准的private Golden绑定，不能将actual复制成expected。Oracle支持 `eq/ge/le`；路径缺失、类型不符、摘要不符均判FAIL。部署/真实网络只在明确启用live并持有现场输入时执行。

下列命令、test_id与回执结构为本release需要交付的测试合同，不是当前仓库已有这些文件或已经执行的声明。验收条目不是PASS清单。

## A-001 — 允许列表执行

### Requirement Refs
REQ-BOUNDARY-001

### Given
一个合法本地会话，录制样本和 OAuth token。

### When
执行登录、OAuth、查询、Worker、ready及注销全流程。

### Then
仅登录请求访问固定Backend一次；Tencent全部命中允许列表；三个禁止路径计数均0。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "network.backend.account_login",
      "op": "eq",
      "expected": 1
    },
    {
      "path": "network.backend.forbidden_sent",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "network.tencent.business_write",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "network.tencent.allowlist_violations",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-001`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_001 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-BOUNDARY-001/A-001.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-002 — 禁止路径及旁路

### Requirement Refs
REQ-BOUNDARY-001

### Given
可计数且默认拒绝的MockTransport。

### When
依次尝试三个旧路径、/health、/api/v1/auth/me、一个百分号编码路径变体、GET登录、302第二跳（共8例）。

### Then
每例BACKEND_ENDPOINT_FORBIDDEN或明确重定向错误；实际第二跳/禁止出站=0。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "network.backend.forbidden_sent",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "network.redirect_second_hops",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "cases.rejected",
      "op": "eq",
      "expected": 8
    }
  ]
}
```

### Evidence
- test id：`TEST-A-002`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_002 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-BOUNDARY-001/A-002.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-003 — 样例字段投影

### Requirement Refs
REQ-AUTH-001

### Given
脱敏样例含role=user、portal_org_role=admin、org_role=null、is_active=true。

### When
网关直接收到成功登录响应。

### Then
创建一个本地用户映射和会话；管理角色保留admin观察；无密码及上游Token列/文件。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "db.new_sessions",
      "op": "eq",
      "expected": 1
    },
    {
      "path": "user.portal_org_role",
      "op": "eq",
      "expected": "admin"
    },
    {
      "path": "secret_scan.backend_tokens",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "secret_scan.password",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-003`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_003 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-AUTH-001/A-003.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-004 — 伪造响应和异常字段

### Requirement Refs
REQ-AUTH-001

### Given
缺user.id/组织、is_active=false、must_change_password=true、needs_org_setup=true、前端自报user的参数化输入。

### When
尝试登录。

### Then
每例固定错误；session新增0；无任何目录补查。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "cases.invalid_response_sessions",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "network.backend.other",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "cases.invalid_response_rejected",
      "op": "eq",
      "expected": 6
    }
  ]
}
```

### Evidence
- test id：`TEST-A-004`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_004 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-AUTH-001/A-004.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-005 — 同身份重复登录

### Requirement Refs
REQ-ID-001

### Given
同一Backend user.id和org_id，账号显示名称已变化。

### When
并发两次成功登录。

### Then
活跃LocalMember数量1；本地member_id不变；user.id原样保留。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "db.active_member_count",
      "op": "eq",
      "expected": 1
    },
    {
      "path": "identity.member_id_after",
      "op": "eq",
      "expected_from": "fixture.member_id_before"
    },
    {
      "path": "identity.backend_user_id",
      "op": "eq",
      "expected_from": "fixture.backend_user_id"
    }
  ]
}
```

### Evidence
- test id：`TEST-A-005`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_005 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-ID-001/A-005.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-006 — 旧ID/跨组织拒绝

### Requirement Refs
REQ-ID-001

### Given
另一个org或只提供姓名推算旧member_id。

### When
尝试关联资源。

### Then
ORG_NOT_ALLOWED或IDENTITY_MIGRATION_REQUIRED；旧owner字段摘要不变。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "cross_org.accepted",
      "op": "eq",
      "expected": false
    },
    {
      "path": "unknown_owner.accepted",
      "op": "eq",
      "expected": false
    },
    {
      "path": "legacy.owner_digest_after",
      "op": "eq",
      "expected_from": "fixture.legacy_owner_digest_before"
    }
  ]
}
```

### Evidence
- test id：`TEST-A-006`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_006 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-ID-001/A-006.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-007 — 会话生命周期

### Requirement Refs
REQ-AUTH-002

### Given
expires_in=86400、TTL=900、可控时钟。

### When
登录；t+899读；t+900读；新登录；注销。

### Then
首次期限900；边界401；旧期限不延长；注销后所有子token401。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "session.ttl_seconds",
      "op": "eq",
      "expected": 900
    },
    {
      "path": "session.status_at_900",
      "op": "eq",
      "expected": 401
    },
    {
      "path": "session.revoked_child_status",
      "op": "eq",
      "expected": 401
    },
    {
      "path": "session.old_expiry_extended",
      "op": "eq",
      "expected": false
    }
  ]
}
```

### Evidence
- test id：`TEST-A-007`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_007 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-AUTH-002/A-007.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-008 — 无远程续期

### Requirement Refs
REQ-AUTH-002

### Given
会话过期且腾讯Token仍有效。

### When
触发数据读取和Worker。

### Then
HTTP401或WAITING_LOGIN；Backend调用0；Tencent新请求0。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "job.state",
      "op": "eq",
      "expected": "WAITING_LOGIN"
    },
    {
      "path": "network.after_expiry.backend",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "network.after_expiry.tencent",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-008`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_008 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-AUTH-002/A-008.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-009 — 管理与业务权限分离

### Requirement Refs
REQ-ACL-001

### Given
样例A在管理名单且portal_org_role=admin，无OAuth授权。

### When
登录并读取runtime-config，再请求正文；随后本人授权确认。

### Then
可读配置；未授权正文拒绝；确认后仅本人连接可读。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "admin.config_status",
      "op": "eq",
      "expected": 200
    },
    {
      "path": "content.before_confirm_allowed",
      "op": "eq",
      "expected": false
    },
    {
      "path": "grant.only_owner_connection",
      "op": "eq",
      "expected": true
    }
  ]
}
```

### Evidence
- test id：`TEST-A-009`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_009 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-ACL-001/A-009.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-010 — B及角色越权

### Requirement Refs
REQ-ACL-001

### Given
B有效登录和自己的有效业务token；A资源已缓存。

### When
B替换meeting/recording/connection ID；或仅is_task_admin=true申请管理。

### Then
404/403；正文返回0字节；不请求Backend搜索。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "content.cross_owner_bytes",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "admin.task_admin_only_allowed",
      "op": "eq",
      "expected": false
    },
    {
      "path": "network.backend.search",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-010`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_010 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-ACL-001/A-010.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-011 — 仅ENV初始化

### Requirement Refs
REQ-CONFIG-001

### Given
只有OAuth三字段+数据库密钥+账号登录配置，没有旧服务Token/Webhook/AKSK。

### When
迁移后两次env-apply。

### Then
两次同application ID；网络0；配置检查退出0；mode=oauth。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "apply.exit_codes",
      "op": "eq",
      "expected": [
        0,
        0
      ]
    },
    {
      "path": "db.env_application_count",
      "op": "eq",
      "expected": 1
    },
    {
      "path": "db.application_id_unchanged",
      "op": "eq",
      "expected": true
    },
    {
      "path": "network.total",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-011`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_011 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-CONFIG-001/A-011.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-012 — 缺值和错误映射

### Requirement Refs
REQ-CONFIG-001

### Given
缺Secret、企业ID/AppID对调的fixture、非ENV受管冲突。

### When
运行配置校验和应用装载。

### Then
错误值不能由猜测修正；CONFIG_INVALID/CONFIG_CONFLICT；不新增重复应用。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "missing_secret.valid",
      "op": "eq",
      "expected": false
    },
    {
      "path": "fixture_wrong_id.self_corrected",
      "op": "eq",
      "expected": false
    },
    {
      "path": "db.duplicate_application_count",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-012`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_012 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-CONFIG-001/A-012.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-013 — 配置更新及保留连接

### Requirement Refs
REQ-CONFIG-002

### Given
已有授权连接，只有允许公司列表或Secret改变。

### When
apply并重启API/Worker。

### Then
app/connection ID不变；generation变更一次；用户Token没有自动标新已验证。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "config.generation_increase",
      "op": "eq",
      "expected": 1
    },
    {
      "path": "db.connection_id_unchanged",
      "op": "eq",
      "expected": true
    },
    {
      "path": "oauth.synthetic_verification",
      "op": "eq",
      "expected": false
    }
  ]
}
```

### Evidence
- test id：`TEST-A-013`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_013 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-CONFIG-002/A-013.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-014 — 漂移/回滚

### Requirement Refs
REQ-CONFIG-002

### Given
非ENV API覆盖或第二进程仍用旧摘要；事务提交前注入异常。

### When
更新配置并发调用。

### Then
ENV_MANAGED_RESOURCE/CONFIG_DRIFT；失败受管行摘要=T0；恢复资料保留。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "api.override_reason",
      "op": "eq",
      "expected": "ENV_MANAGED_RESOURCE"
    },
    {
      "path": "runtime.old_generation_reason",
      "op": "eq",
      "expected": "CONFIG_DRIFT"
    },
    {
      "path": "rollback.managed_digest_after",
      "op": "eq",
      "expected_from": "fixture.managed_digest_t0"
    }
  ]
}
```

### Evidence
- test id：`TEST-A-014`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_014 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-CONFIG-002/A-014.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-015 — 无Portal授权

### Requirement Refs
REQ-OAUTH-001

### Given
无PORTAL_BASE_URL，本地会话有效且ENV默认应用存在。

### When
发起授权、模拟合法腾讯回调、查询事务。

### Then
URL使用正确corp_id/sdk_id；只换码1次；303到网关；记录connection_id。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "network.tencent.exchange_count",
      "op": "eq",
      "expected": 1
    },
    {
      "path": "callback.status",
      "op": "eq",
      "expected": 303
    },
    {
      "path": "callback.target_origin_is_gateway",
      "op": "eq",
      "expected": true
    },
    {
      "path": "transaction.connection_present",
      "op": "eq",
      "expected": true
    }
  ]
}
```

### Evidence
- test id：`TEST-A-015`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_015 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-OAUTH-001/A-015.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-016 — state攻击与漏密

### Requirement Refs
REQ-OAUTH-001

### Given
过期state、跨应用state、会话到期、外站return_to、重复auth_code。

### When
调用回调/授权入口。

### Then
错误固定；不发额外换码；输出URL/日志无凭据。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "cases.rejected",
      "op": "eq",
      "expected": 5
    },
    {
      "path": "network.extra_exchange",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "output.secrets_found",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-016`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_016 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-OAUTH-001/A-016.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-017 — 未知公司再确认

### Requirement Refs
REQ-OAUTH-002

### Given
允许表为空、换码返回真实非空OpenCorpID。

### When
保存待核验；运维加精确ID；本人确认。

### Then
待核验期间Tencent资源GET=0；确认user_info一致后ACTIVE且本人scope生效。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "connection.initial_state",
      "op": "eq",
      "expected": "PENDING_CORP_APPROVAL"
    },
    {
      "path": "network.before_approval.resource_get",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "connection.final_state",
      "op": "eq",
      "expected": "ACTIVE"
    },
    {
      "path": "connection.identity_matches",
      "op": "eq",
      "expected": true
    }
  ]
}
```

### Evidence
- test id：`TEST-A-017`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_017 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-OAUTH-002/A-017.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-018 — 企业/用户错配

### Requirement Refs
REQ-OAUTH-002

### Given
空OpenCorpID、不同员工抢占同open_id、不同user_info.open_id。

### When
请求确认。

### Then
CORP_REJECTED或IDENTITY_CONFLICT；无ACCESS授权新增。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "empty_corp.allowed",
      "op": "eq",
      "expected": false
    },
    {
      "path": "other_owner.allowed",
      "op": "eq",
      "expected": false
    },
    {
      "path": "db.unauthorized_grants_added",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-018`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_018 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-OAUTH-002/A-018.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-019 — 并发刷新与临时恢复

### Requirement Refs
REQ-OAUTH-003

### Given
同连接将到期，两个Worker，本地快照有效。

### When
并发刷新一次成功或一次5xx后重试。

### Then
有效generation单调递增；5xx不成为永久重新授权；Backend计数0。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "refresh.successful_new_generation_count",
      "op": "eq",
      "expected": 1
    },
    {
      "path": "refresh.temporary_fault_is_reauth",
      "op": "eq",
      "expected": false
    },
    {
      "path": "network.backend.total",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-019`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_019 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-OAUTH-003/A-019.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-020 — 失效与旁路

### Requirement Refs
REQ-OAUTH-003

### Given
腾讯明确失效/owner会话过期/刷新回open_id改变。

### When
触发维护。

### Then
REAUTH_REQUIRED/暂停/BLOCKED；无AKSK、STS、Backend目录请求。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "invalid_grant.state",
      "op": "eq",
      "expected": "REAUTH_REQUIRED"
    },
    {
      "path": "expired_identity.refresh_calls",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "network.aksk_or_sts",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-020`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_020 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-OAUTH-003/A-020.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-021 — 本地令牌交换

### Requirement Refs
REQ-CLIENT-001

### Given
A有确认连接和限定读scope的客户端。

### When
用本地session交换并读取A会议。

### Then
Backend计数0；token受众正确；expires<=session；返回本人的数据。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "network.backend.total",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "token.audience_suffix",
      "op": "eq",
      "expected": "/api/v1"
    },
    {
      "path": "token.expires_at",
      "op": "le",
      "expected_from": "session.expires_at"
    },
    {
      "path": "content.owner_matches",
      "op": "eq",
      "expected": true
    }
  ]
}
```

### Evidence
- test id：`TEST-A-021`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_021 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-CLIENT-001/A-021.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-022 — 外部JWT和scope越权

### Requirement Refs
REQ-CLIENT-001

### Given
用户提供的BackendJWT样式占位值、伪造userJSON、请求写scope。

### When
交换/访问接口。

### Then
401/403/410；业务写出站0；不能通过解码sub获得身份。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "backend_jwt.accepted",
      "op": "eq",
      "expected": false
    },
    {
      "path": "forged_user.accepted",
      "op": "eq",
      "expected": false
    },
    {
      "path": "write_scope.accepted",
      "op": "eq",
      "expected": false
    },
    {
      "path": "network.tencent.business_write",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-022`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_022 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-CLIENT-001/A-022.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-023 — 历史完整分页

### Requirement Refs
REQ-QUERY-001

### Given
三个history页、跨窗口重复ID、目标在第三页。

### When
提交USER_WINDOW并读results。

### Then
实际history页请求全部完成；去重后count等于期望；目标provider ID存在。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "query.pages_read",
      "op": "eq",
      "expected_from": "fixture.total_pages"
    },
    {
      "path": "query.distinct_meetings",
      "op": "eq",
      "expected_from": "fixture.distinct_meetings"
    },
    {
      "path": "query.sample_found",
      "op": "eq",
      "expected": true
    }
  ]
}
```

### Evidence
- test id：`TEST-A-023`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_023 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-QUERY-001/A-023.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-024 — 空结果与越权

### Requirement Refs
REQ-QUERY-001

### Given
所有页空/中间页缺失/target_member_id指他人。

### When
提交查询并生成报告。

### Then
空返回SUCCEEDED_EMPTY但Golden不PASS；缺页FAILED；他人403且0上游。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "empty.state",
      "op": "eq",
      "expected": "SUCCEEDED_EMPTY"
    },
    {
      "path": "empty.golden_pass",
      "op": "eq",
      "expected": false
    },
    {
      "path": "partial.state",
      "op": "eq",
      "expected": "FAILED"
    },
    {
      "path": "foreign_member.upstream_calls",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-024`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_024 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-QUERY-001/A-024.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-025 — 录制发现与窗口拆分

### Requirement Refs
REQ-QUERY-002

### Given
无本地资源、65天窗口、每个片段多页、非目标干扰记录。

### When
分别运行USER_RECORDINGS与RECORDINGS。

### Then
所有上游时间窗<=31天；全部页遍历；精确目标结果不混其他会议。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "query.max_window_seconds_lte_31d",
      "op": "eq",
      "expected": true
    },
    {
      "path": "query.pages_read",
      "op": "eq",
      "expected_from": "fixture.total_record_pages"
    },
    {
      "path": "query.foreign_meetings_in_filtered_result",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-025`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_025 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-QUERY-002/A-025.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-026 — 录制权限和假空成功

### Requirement Refs
REQ-QUERY-002

### Given
history可见但records拒绝、零record_files、非目标数据。

### When
运行录制样本验收。

### Then
上游权限原因保留；没有录制不能记内容提取PASS；无企业接口调用。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "denied.reason",
      "op": "eq",
      "expected": "UPSTREAM_PERMISSION_DENIED"
    },
    {
      "path": "empty.content_gate_pass",
      "op": "eq",
      "expected": false
    },
    {
      "path": "network.tencent.corp_records",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-026`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_026 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-QUERY-002/A-026.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-027 — 三页转写完整导出

### Requirement Refs
REQ-CONTENT-001

### Given
3页、边界重复段、已知原文和时间戳。

### When
拉取完整转写并分页读回。

### Then
去重后段落数与fixture相等；READY/complete=true；hash/页数匹配。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "transcript.paragraph_count",
      "op": "eq",
      "expected_from": "fixture.paragraph_count"
    },
    {
      "path": "transcript.source_page_count",
      "op": "eq",
      "expected": 3
    },
    {
      "path": "transcript.state",
      "op": "eq",
      "expected": "READY"
    },
    {
      "path": "transcript.is_complete",
      "op": "eq",
      "expected": true
    },
    {
      "path": "transcript.content_hash",
      "op": "eq",
      "expected_from": "fixture.expected_content_hash"
    }
  ]
}
```

### Evidence
- test id：`TEST-A-027`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_027 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-CONTENT-001/A-027.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-028 — 中断与变更

### Requirement Refs
REQ-CONTENT-001

### Given
第二页故障、pid不推进、续传边界正文变化、越权录制。

### When
读取/恢复。

### Then
无不完整READY；错误可定位；越权0正文/0腾讯请求。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "partial.ready_count",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "stuck_cursor.failed",
      "op": "eq",
      "expected": true
    },
    {
      "path": "unauthorized.upstream_calls",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "source_changed.restarts_lte_one",
      "op": "eq",
      "expected": true
    }
  ]
}
```

### Evidence
- test id：`TEST-A-028`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_028 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-CONTENT-001/A-028.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-029 — 元宝纪要兼容

### Requirement Refs
REQ-CONTENT-002

### Given
minute有内容，todo为空或不存在。

### When
获取并导出Markdown。

### Then
READY；minute原样保存；todo不造成失败；model/text_type记录准确。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "minutes.state",
      "op": "eq",
      "expected": "READY"
    },
    {
      "path": "minutes.llm",
      "op": "eq",
      "expected": 3
    },
    {
      "path": "minutes.text_type",
      "op": "eq",
      "expected": 2
    },
    {
      "path": "export.minute_bytes_hash",
      "op": "eq",
      "expected_from": "fixture.minute_utf8_hash"
    }
  ]
}
```

### Evidence
- test id：`TEST-A-029`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_029 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-CONTENT-002/A-029.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-030 — 空纪要和冒充结果

### Requirement Refs
REQ-CONTENT-002

### Given
空minute、上游无权、测试LLM spy。

### When
运行提取。

### Then
空不READY；权限错误保留；LLM/翻译调用数0。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "empty.ready_count",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "denied.reason",
      "op": "eq",
      "expected": "UPSTREAM_PERMISSION_DENIED"
    },
    {
      "path": "network.llm_calls",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-030`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_030 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-CONTENT-002/A-030.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-031 — 到期暂停与恢复

### Requirement Refs
REQ-JOB-001

### Given
长转写第三页前会话到期，检查点已保存。

### When
Worker执行；同owner/client新登录resume。

### Then
到期后0腾讯新调用；WAITING_LOGIN；恢复从已验证边界继续；完整后成功。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "expired.state",
      "op": "eq",
      "expected": "WAITING_LOGIN"
    },
    {
      "path": "expired.new_upstream_calls",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "resumed.complete",
      "op": "eq",
      "expected": true
    },
    {
      "path": "resumed.owner_unchanged",
      "op": "eq",
      "expected": true
    }
  ]
}
```

### Evidence
- test id：`TEST-A-031`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_031 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-JOB-001/A-031.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-032 — 无限重试/越权恢复

### Requirement Refs
REQ-JOB-001

### Given
上游永久403、两Worker抢租、B恢复A作业。

### When
执行故障注入。

### Then
403首次即失败；旧lease0发布；B403；后台Backend调用0。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "permission_denied.attempts",
      "op": "eq",
      "expected": 1
    },
    {
      "path": "stale_lease.publish_count",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "foreign_resume.status",
      "op": "eq",
      "expected": 403
    },
    {
      "path": "network.backend.total",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-032`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_032 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-JOB-001/A-032.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-033 — 完整文件与摘要

### Requirement Refs
REQ-EXPORT-001

### Given
已知会议、录制、3页完整转写及minute文本。

### When
导出并二次同输入导出。

### Then
6类文件及manifest正确；第二次摘要不变；正文与manifest字节count匹配。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "export.required_file_count",
      "op": "eq",
      "expected": 6
    },
    {
      "path": "export.all_digest_matches",
      "op": "eq",
      "expected": true
    },
    {
      "path": "export.second_run_changed_bytes",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-033`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_033 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-EXPORT-001/A-033.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-034 — 路径与伪完成

### Requirement Refs
REQ-EXPORT-001

### Given
../、symlink、磁盘满、partial正文、同路径异内容。

### When
尝试导出。

### Then
非零退出；外部文件摘要不变；partial无完成manifest。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "unsafe.export_exit_nonzero",
      "op": "eq",
      "expected": true
    },
    {
      "path": "unsafe.outside_root_bytes_changed",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "partial.complete_manifest_exists",
      "op": "eq",
      "expected": false
    }
  ]
}
```

### Evidence
- test id：`TEST-A-034`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_034 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-EXPORT-001/A-034.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-035 — 空库及已证迁移

### Requirement Refs
REQ-MIGRATE-001

### Given
空库或明确owner映射的旧OAuth记录。

### When
升级两次后本地登录。

### Then
空库可用；有证映射一次完成；禁止端点0；重复迁移0重复行。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "migration.rerun_duplicate_rows",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "legacy_adopted.owner_evidence_matches",
      "op": "eq",
      "expected": true
    },
    {
      "path": "new_install.requires_backend_service_token",
      "op": "eq",
      "expected": false
    }
  ]
}
```

### Evidence
- test id：`TEST-A-035`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_035 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-MIGRATE-001/A-035.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-036 — 不明owner与失败回滚

### Requirement Refs
REQ-MIGRATE-001

### Given
旧member_id与user.id无可信映射，或迁移中断。

### When
迁移/回滚。

### Then
旧记录保留并不可读；T0摘要一致或ROLLBACK_FAILED保留备份；不请求旧接口。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "unknown_owner.deleted_rows",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "unknown_owner.read_allowed",
      "op": "eq",
      "expected": false
    },
    {
      "path": "rollback.restored_or_preserved_recovery",
      "op": "eq",
      "expected": true
    },
    {
      "path": "network.backend.forbidden_sent",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-036`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_036 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-MIGRATE-001/A-036.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-037 — 最小独立部署

### Requirement Refs
REQ-DEPLOY-001

### Given
只有DB/API/Worker，远端唯一登录端点，无Portal和旧身份接口。

### When
迁移、env-apply、启动重启、登录、OAuth。

### Then
无旧依赖配置仍启动；readiness不探Backend；数据/授权重启保留。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "deployment.no_portal_required",
      "op": "eq",
      "expected": true
    },
    {
      "path": "deployment.config_check_exit",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "restart.state_preserved",
      "op": "eq",
      "expected": true
    },
    {
      "path": "network.backend.health",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-037`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_037 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-DEPLOY-001/A-037.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-038 — 网络与配置失败

### Requirement Refs
REQ-DEPLOY-001

### Given
callback证书不合法、出口不符、旧服务占端口、不同代次Worker。

### When
执行部署检查。

### Then
对应阶段BLOCKED/FAIL；不覆盖原业务；不将/health成功作为OAuth通过。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "unsafe.network_gate_pass",
      "op": "eq",
      "expected": false
    },
    {
      "path": "conflict.existing_service_changed",
      "op": "eq",
      "expected": false
    },
    {
      "path": "local_ready.claims_data_verified",
      "op": "eq",
      "expected": false
    }
  ]
}
```

### Evidence
- test id：`TEST-A-038`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_038 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-DEPLOY-001/A-038.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-039 — 真实单通道调用

### Requirement Refs
REQ-CMD-001

### Given
Mock HTTP验证脚本行为 + 现场样本配置，无AKSK/STS。

### When
运行新oauth-readonly scope。

### Then
真实请求有trace；目标文件非空且可核对；不依赖AKSK证据。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "tool.gateway_calls",
      "op": "ge",
      "expected": 1
    },
    {
      "path": "tool.requests_old_identity",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "tool.requires_aksk_sts",
      "op": "eq",
      "expected": false
    },
    {
      "path": "tool.contract_matches",
      "op": "eq",
      "expected": true
    }
  ]
}
```

### Evidence
- test id：`TEST-A-039`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_039 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-CMD-001/A-039.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-040 — 占位与错版本

### Requirement Refs
REQ-CMD-001

### Given
MEETING_LIVE未启用、sample缺失、脚本只GET health/cache、源码不匹配。

### When
要求live验收并生成报告。

### Then
退出非零；NOT_RUN/BLOCKED不PASS；无旧run证据混入。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "not_run.exit_nonzero",
      "op": "eq",
      "expected": true
    },
    {
      "path": "missing_sample.exit_nonzero",
      "op": "eq",
      "expected": true
    },
    {
      "path": "evidence.cross_run_reused",
      "op": "eq",
      "expected": false
    }
  ]
}
```

### Evidence
- test id：`TEST-A-040`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_040 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-CMD-001/A-040.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-041 — 真实内部系统 OAuth 数据提取

### Requirement Refs
REQ-CMD-001

### Given
指定白名单服务器、真实账号A、ENV OAuth应用、A本人创建且转写/元宝纪要可见的非敏感样本、独立内部客户端和本次绑定SHA。

### When
通过新kit从账号登录开始完成OAuth、用户录制分页、完整转写/纪要获取与私有落盘。

### Then
真实上游OAuth/records/transcript/minutes调用均大于0；provider样本ID精确匹配；文本文件非空且完整；禁止Backend路径及Tencent业务写发送0；不要求AKSK或STS。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "network.tencent.oauth_exchange",
      "op": "ge",
      "expected": 1
    },
    {
      "path": "network.tencent.records",
      "op": "ge",
      "expected": 1
    },
    {
      "path": "network.tencent.transcript",
      "op": "ge",
      "expected": 1
    },
    {
      "path": "network.tencent.minutes",
      "op": "ge",
      "expected": 1
    },
    {
      "path": "sample.provider_ids_match",
      "op": "eq",
      "expected": true
    },
    {
      "path": "export.transcript_complete",
      "op": "eq",
      "expected": true
    },
    {
      "path": "export.minutes_nonempty",
      "op": "eq",
      "expected": true
    },
    {
      "path": "network.backend.forbidden_sent",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "network.tencent.business_write",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "test.synthetic",
      "op": "eq",
      "expected": false
    }
  ]
}
```

### Evidence
- test id：`TEST-A-041`；门禁：REQUIRED_LIVE。
- command：`python -m pytest tests/live/test_oauth_readonly_login_env.py -k test_a_041 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-CMD-001/A-041.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-042 — 秘密与请求范围

### Requirement Refs
REQ-SEC-001

### Given
所有fake-secret含唯一标记，A/B各有授权资源。

### When
执行登录、OAuth、刷新、读取、异常和导出。

### Then
日志/evidence无标记；私有OAuth密文不可明文搜索；B正文0字节。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "secret_scan.log_matches",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "secret_scan.evidence_matches",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "db.plaintext_oauth_token_matches",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "cross_owner.content_bytes",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-042`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_042 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-SEC-001/A-042.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-043 — 攻击矩阵

### Requirement Refs
REQ-SEC-001

### Given
重定向到外站、路径穿越、symlink、前端admin、会议信息含shell命令、连续失败登录。

### When
运行参数化请求。

### Then
固定拒绝/429；任意执行0；禁止网络0；外目录写0。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "attack.exec_count",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "attack.outside_write_bytes",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "attack.forbidden_network_sent",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "login.rate_limited_status",
      "op": "eq",
      "expected": 429
    }
  ]
}
```

### Evidence
- test id：`TEST-A-043`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_043 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-SEC-001/A-043.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-044 — 证据可判定

### Requirement Refs
REQ-EVID-001

### Given
完整本次positive和negative测试回执及Golden样本文件。

### When
生成oauth-readonly报告。

### Then
所有Required=PASS才exit0；source SHA/manifest/count/zero-endpoint均有oracle。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "report.all_required_have_oracles",
      "op": "eq",
      "expected": true
    },
    {
      "path": "report.all_required_pass",
      "op": "eq",
      "expected": true
    },
    {
      "path": "report.exit_code",
      "op": "eq",
      "expected": 0
    }
  ]
}
```

### Evidence
- test id：`TEST-A-044`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_044 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-EVID-001/A-044.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-045 — 假证据与未批准

### Requirement Refs
REQ-EVID-001

### Given
缺一个必需AC、改一个导出字节、全部live skip、只有旧测试报告。

### When
生成报告或申请plan。

### Then
非零/EVIDENCE_INCOMPLETE/EVIDENCE_TAMPERED；PRD仍REVIEW。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "missing_evidence.exit_nonzero",
      "op": "eq",
      "expected": true
    },
    {
      "path": "tampered_evidence.reason",
      "op": "eq",
      "expected": "EVIDENCE_TAMPERED"
    },
    {
      "path": "live_skipped.exit_nonzero",
      "op": "eq",
      "expected": true
    },
    {
      "path": "prd.status",
      "op": "eq",
      "expected_from": "fixture.prd_status_before"
    }
  ]
}
```

### Evidence
- test id：`TEST-A-045`；门禁：REQUIRED_OFFLINE。
- command：`python -m pytest tests/acceptance/test_oauth_readonly_login_env.py -k test_a_045 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-EVID-001/A-045.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

## A-046 — 真实跨员工隔离与版本证据

### Requirement Refs
REQ-EVID-001

### Given
A已有导出；B使用自己的真实账号和合法客户端会话，具备自己的正常授权或正向读取控制；源码/kit镜像实际版本已记录。

### When
B访问A录制并生成整个oauth-readonly报告。

### Then
B正向控制成功而A内容返回404/403且0正文；全部必需现场证据同run_id/source_sha；缺任何必需证据则报告非零。

### Oracle
```json
{
  "type": "conjunction",
  "assertions": [
    {
      "path": "b.positive_control",
      "op": "eq",
      "expected": true
    },
    {
      "path": "b.read_a_denied",
      "op": "eq",
      "expected": true
    },
    {
      "path": "b.read_a_content_bytes",
      "op": "eq",
      "expected": 0
    },
    {
      "path": "report.same_run_and_sha",
      "op": "eq",
      "expected": true
    },
    {
      "path": "missing_required.exit_nonzero",
      "op": "eq",
      "expected": true
    },
    {
      "path": "test.synthetic",
      "op": "eq",
      "expected": false
    }
  ]
}
```

### Evidence
- test id：`TEST-A-046`；门禁：REQUIRED_LIVE。
- command：`python -m pytest tests/live/test_oauth_readonly_login_env.py -k test_a_046 -q`。
- exit code：测试断言全部满足时0；用例负向HTTP不是测试进程失败，测试进程验证拒绝后退出0；BLOCKED/SKIPPED不能代替必需现场证据。
- pre digest：fixture/Golden绑定和受管业务T0；post digest：受管业务或导出/证据清单（规则§13）；不适用时记录N/A理由，不编造摘要。
- artifact：`evidence/<run_id>/REQ-EVID-001/A-046.json` + 测试结果 + 安全网络计数；receipt的facts支持上述每项Oracle。

# 21. Acceptance Input Matrix

| 输入类 | 精确样例 | 涉及需求 | 预期 |
|---|---|---|---|
| normal | 用户响应形状脱敏fixture；有效本人OAuth | AUTH/ID/OAUTH/QUERY/CONTENT | 按合同提取已知数据 |
| empty | 组织ID空；公司允许表空；历史0条；minute空 | AUTH/CONFIG/OAUTH/QUERY/CONTENT | 拒绝/待公司审批/SUCCEEDED_EMPTY/NOT_READY |
| missing | Secret、user.id、expires_in、record_files缺失 | AUTH/CONFIG/QUERY | 配置或协议失败；不补查身份 |
| existing | 相同ENV应用、同用户再登录、已有导出 | ID/CONFIG/EXPORT | 同ID幂等；会话独立，不覆盖异字节 |
| duplicate | 并发登录、重复state、重复页、两Worker | ID/OAUTH/QUERY/JOB | 活跃唯一行；state拒绝；页去重 |
| drifted | 旧ENV代次、手工改受管字段、改导出文件 | CONFIG/MIGRATE/EXPORT | CONFIG_DRIFT/EXPORT_CONFLICT；保留 |
| partial | 转写第2页中断；导出临时文件 | CONTENT/JOB/EXPORT | PARTIAL；无READY/完成manifest |
| invalid | 请求中user/role、错org、外站return_to、过期state | AUTH/ACL/OAUTH/SEC | 明确错误；禁止出站0 |
| boundary | TTL899/900秒；31/90天；100000结果；16MiB | AUTH/QUERY/CONTENT | 边界按合同；超限非成功 |
| retry | 429、5xx、等待生成、刷新冲突 | OAUTH/JOB/CONTENT | 有限退避；会话过期暂停 |
| failure | DB失败、磁盘满、TLS非法、登录超时 | AUTH/CONFIG/OAUTH/EXPORT/DEPLOY | 局部回滚/明确未知；不换接口 |
| rollback | ENV/身份迁移失败、恢复失败 | CONFIG/MIGRATE | 恢复T0或ROLLBACK_FAILED保留恢复包 |

每个高风险需求用参数化fixture覆盖适用行；case数与expected在测试准备manifest固定。默认输入存在不等于权限已授予。

# 22. Negative Acceptance

每个包含禁止行为的需求都有负向验收。拒绝指业务错误符合Oracle，负向测试本身验证拒绝后返回0。

| Requirement | Negative Acceptance | 覆盖 |
|---|---|---|

| REQ-BOUNDARY-001 | A-002 | 禁止路径及旁路 |

| REQ-AUTH-001 | A-004 | 伪造响应和异常字段 |

| REQ-ID-001 | A-006 | 旧ID/跨组织拒绝 |

| REQ-AUTH-002 | A-008 | 无远程续期 |

| REQ-ACL-001 | A-010 | B及角色越权 |

| REQ-CONFIG-001 | A-012 | 缺值和错误映射 |

| REQ-CONFIG-002 | A-014 | 漂移/回滚 |

| REQ-OAUTH-001 | A-016 | state攻击与漏密 |

| REQ-OAUTH-002 | A-018 | 企业/用户错配 |

| REQ-OAUTH-003 | A-020 | 失效与旁路 |

| REQ-CLIENT-001 | A-022 | 外部JWT和scope越权 |

| REQ-QUERY-001 | A-024 | 空结果与越权 |

| REQ-QUERY-002 | A-026 | 录制权限和假空成功 |

| REQ-CONTENT-001 | A-028 | 中断与变更 |

| REQ-CONTENT-002 | A-030 | 空纪要和冒充结果 |

| REQ-JOB-001 | A-032 | 无限重试/越权恢复 |

| REQ-EXPORT-001 | A-034 | 路径与伪完成 |

| REQ-MIGRATE-001 | A-036 | 不明owner与失败回滚 |

| REQ-DEPLOY-001 | A-038 | 网络与配置失败 |

| REQ-CMD-001 | A-040 | 占位与错版本 |

| REQ-SEC-001 | A-043 | 攻击矩阵 |

| REQ-EVID-001 | A-045 | 假证据与未批准 |

# 23. Failure Injection

| FI | 注入位置 | 确定后置状态 | 验收归属 |
|---|---|---|---|
| FI-01 | 发Backend登录前网络阻断 | 无会话；LOGIN_UPSTREAM_UNAVAILABLE；无fallback | AUTH-001负向 |
| FI-02 | Backend成功、本地提交前DB错误 | 上游登录可能发生；本地会话0；不重试密码 | AUTH-001负向 |
| FI-03 | ENV字段写后、Projection提交前 | 受管字段摘要=T0，配置未发布 | CONFIG-002负向 |
| FI-04 | state消费、换码返回前超时 | OUTCOME_UNKNOWN；不重放 | OAUTH-001负向 |
| FI-05 | Tencent返回Token、入库提交前 | 不ACTIVE、不返回Token；事务失败记录 | OAUTH-001/003负向 |
| FI-06 | user_info完成、confirm提交前Session过期 | 无owner grant新增；LOGIN_REQUIRED | OAUTH-002负向 |
| FI-07 | 刷新POST后旧Worker晚提交 | CAS拒绝旧写；新代次保留 | OAUTH-003负向 |
| FI-08 | 第N页读后、checkpoint提交前崩溃 | 已提交页保留；未提交页重读去重 | QUERY-001/002负向 |
| FI-09 | 第2页前本地限流 | 等待/续租，不加失败；游标不退回0 | CONTENT-001/JOB-001正向 |
| FI-10 | 转写恢复边界正文变化 | 不混版本；重启一次仍变则SOURCE_CHANGED | CONTENT-001负向 |
| FI-11 | 读取完成、READY提交前撤权 | 不发布可读新版本；缓存不绕权 | ACL-001/CONTENT-001负向 |
| FI-12 | 文件写后、rename前失败 | 最终路径无半文件；manifest不完整 | EXPORT-001负向 |
| FI-13 | 迁移owner一半失败 | 受管owner摘要=T0；未知资源不变 | MIGRATE-001负向 |
| FI-14 | 配置/迁移恢复失败 | ROLLBACK_FAILED；停相关服务；保留备份 | MIGRATE/CONFIG负向 |
| FI-15 | 证据文件被改一个字节 | EVIDENCE_TAMPERED；report非零 | EVID-001负向 |
| FI-16 | Worker维护触发旧身份适配器 | 出站阻断；forbidden_sent=0；测试定位违规点 | BOUNDARY-001负向 |

# 24. Evidence Contract

## 24.1 Evidence 不只是状态标签

```json
{
  "schema": "mg.oauth-readonly.evidence/1.1",
  "run_id": "<本次唯一运行ID>",
  "acceptance_id": "A-001",
  "status": "NOT_RUN",
  "requirement_ids": ["REQ-BOUNDARY-001"],
  "test_ids": ["TEST-A-001"],
  "repository": "smc-copilot/meeting-gateway",
  "source_sha": "<现场实际部署提交>",
  "dirty_tree_digest": null,
  "kit_digest": "<工具目录摘要>",
  "command_template": "<不含密码或Token的命令>",
  "exit_code": null,
  "started_at": null,
  "finished_at": null,
  "oracle": {"type":"conjunction", "assertions":[]},
  "facts": {},
  "evidence_files": [],
  "redaction_policy": "credential-and-content-excluded/1"
}
```

执行时填真实字段、facts和非空oracle；模板NOT_RUN不是合格Evidence。Secret文件、正文、Token、原始登录响应不放公开evidence；正文只在private，evidence列受控文件别名、摘要、字节数。

## 24.2 Evidence Integrity

证据关联源仓库、基线/实施SHA、分支、dirty状态、镜像digest、命令、UTC时间、Python/工具版本、部署别名、单文件SHA256及目录manifest。实施后的实际SHA与本PRD基线SHA分开记录。不同run、不同commit或不同身份模式证据不可拼成PASS。

forbidden_sent由集中HTTP适配器计数与测试传输探针证明，现场配合出站网络设施脱敏目标计数复核。不得保存含密码的抓包。没有请求全覆盖证据时此项BLOCKED，不能从空日志推断0调用。

# 25. Release Gate

门禁名：`oauth-readonly-login-env`。

Required集合为§20全部离线正负验收及两个真实Golden验收。任何Required非PASS，发布门禁FAIL且报告进程非零。SKIPPED、BLOCKED、NOT_RUN、空样本不等于PASS。

退出码：0=所有Required PASS；1=断言/接口结果FAIL；2=输入/环境/真实证据BLOCKED；3=证据摘要篡改。不能把BLOCKED转换为0。

AK/SK、STS、创建、视频下载、MCP、腾讯事件、内部事件投递为`NOT_APPLICABLE_TO_SCOPE`，不是必需但被跳过的项；不表示它们已验证。

LOCAL_READY、LOGIN_VERIFIED、OAUTH_VERIFIED、DATA_VERIFIED分别记录；最后连同负向、完整导出和禁止端点证据满足Required才是本scope PASS。

# 26. Golden Consumer / Real-world Acceptance

真实环境使用指定两个目录；Hermes是运维执行者，不自动获得会议智能体委托。账号由操作员交互输入。

绑定文件：gateway repo/SHA/clean或dirty摘要、kit摘要、镜像digest、migration head、配置generation、实际HTTPS入口、API/Worker出口、唯一Backend登录观测、A/B测试别名、provider_meeting_id/provider_record_file_id、查询窗口、腾讯端目标纪要可见的人工证据别名。

业务source digest为开始前批准的sample manifest；不含凭证。前后snapshot记录本地受管计数/状态、用户文件摘要、腾讯业务写次数。只读测试不创建会议制造sample；缺sample则BLOCKED。

A经唯一登录、Tencent OAuth和本人确认，从用户录制列表取得sample完整转写及元宝纪要，保存文件。B有自己的合法会话与正向控制，验证A正文拒绝。Synthetic覆盖错误/并发/分页/时钟；Real覆盖真正登录、Tencent权限、网络和资源；不能互相替代。

# 27. Requirement Traceability Matrix

| Requirement | Invariant | Acceptance | Test | Evidence | Release Gate |
|---|---|---|---|---|---|

| REQ-BOUNDARY-001 | INV-001 | A-001, A-002 | TEST-A-001, TEST-A-002 | `evidence/<run_id>/REQ-BOUNDARY-001/` | REQUIRED |

| REQ-AUTH-001 | INV-002 | A-003, A-004 | TEST-A-003, TEST-A-004 | `evidence/<run_id>/REQ-AUTH-001/` | REQUIRED |

| REQ-ID-001 | INV-003 | A-005, A-006 | TEST-A-005, TEST-A-006 | `evidence/<run_id>/REQ-ID-001/` | REQUIRED |

| REQ-AUTH-002 | INV-004 | A-007, A-008 | TEST-A-007, TEST-A-008 | `evidence/<run_id>/REQ-AUTH-002/` | REQUIRED |

| REQ-ACL-001 | INV-005 | A-009, A-010 | TEST-A-009, TEST-A-010 | `evidence/<run_id>/REQ-ACL-001/` | REQUIRED |

| REQ-CONFIG-001 | INV-006 | A-011, A-012 | TEST-A-011, TEST-A-012 | `evidence/<run_id>/REQ-CONFIG-001/` | REQUIRED |

| REQ-CONFIG-002 | INV-007 | A-013, A-014 | TEST-A-013, TEST-A-014 | `evidence/<run_id>/REQ-CONFIG-002/` | REQUIRED |

| REQ-OAUTH-001 | INV-008 | A-015, A-016 | TEST-A-015, TEST-A-016 | `evidence/<run_id>/REQ-OAUTH-001/` | REQUIRED |

| REQ-OAUTH-002 | INV-009 | A-017, A-018 | TEST-A-017, TEST-A-018 | `evidence/<run_id>/REQ-OAUTH-002/` | REQUIRED |

| REQ-OAUTH-003 | INV-010 | A-019, A-020 | TEST-A-019, TEST-A-020 | `evidence/<run_id>/REQ-OAUTH-003/` | REQUIRED |

| REQ-CLIENT-001 | INV-011 | A-021, A-022 | TEST-A-021, TEST-A-022 | `evidence/<run_id>/REQ-CLIENT-001/` | REQUIRED |

| REQ-QUERY-001 | INV-012 | A-023, A-024 | TEST-A-023, TEST-A-024 | `evidence/<run_id>/REQ-QUERY-001/` | REQUIRED |

| REQ-QUERY-002 | INV-013 | A-025, A-026 | TEST-A-025, TEST-A-026 | `evidence/<run_id>/REQ-QUERY-002/` | REQUIRED |

| REQ-CONTENT-001 | INV-014 | A-027, A-028 | TEST-A-027, TEST-A-028 | `evidence/<run_id>/REQ-CONTENT-001/` | REQUIRED |

| REQ-CONTENT-002 | INV-015 | A-029, A-030 | TEST-A-029, TEST-A-030 | `evidence/<run_id>/REQ-CONTENT-002/` | REQUIRED |

| REQ-JOB-001 | INV-016 | A-031, A-032 | TEST-A-031, TEST-A-032 | `evidence/<run_id>/REQ-JOB-001/` | REQUIRED |

| REQ-EXPORT-001 | INV-017 | A-033, A-034 | TEST-A-033, TEST-A-034 | `evidence/<run_id>/REQ-EXPORT-001/` | REQUIRED |

| REQ-MIGRATE-001 | INV-018 | A-035, A-036 | TEST-A-035, TEST-A-036 | `evidence/<run_id>/REQ-MIGRATE-001/` | REQUIRED |

| REQ-DEPLOY-001 | INV-019 | A-037, A-038 | TEST-A-037, TEST-A-038 | `evidence/<run_id>/REQ-DEPLOY-001/` | REQUIRED |

| REQ-CMD-001 | INV-020 | A-039, A-040, A-041 | TEST-A-039, TEST-A-040, TEST-A-041 | `evidence/<run_id>/REQ-CMD-001/` | REQUIRED |

| REQ-SEC-001 | INV-021 | A-042, A-043 | TEST-A-042, TEST-A-043 | `evidence/<run_id>/REQ-SEC-001/` | REQUIRED |

| REQ-EVID-001 | INV-022 | A-044, A-045, A-046 | TEST-A-044, TEST-A-045, TEST-A-046 | `evidence/<run_id>/REQ-EVID-001/` | REQUIRED |

强制条款缺AC、AC缺Test、Test缺Oracle则PRD结构校验失败；真实Required无Evidence则Release BLOCKED/非零。测试文件存在不满足Evidence要求。

# 28. Plan Generation Contract

只有审批并变更为`APPROVED_FOR_PLAN`后生成正式.plan.md；当前REVIEW。

## 28.1 Semantic Gap Check

身份键、Session期限、公司审批、ENV所有者、分页、空数据、重试、事务和回滚已有唯一行为。不能生成额外Backend接口。Secret、HTTPS入口、sample与实际Backend版本是运行输入；合同不符则BLOCKED，不自行猜请求字段。

## 28.2 Requirement Coverage Check

各需求有ID、输入、前置、SOT、状态、副作用、所有者、幂等、失败、后置、Invariant、错误、AC和Evidence。计划逐项引用，不合并成含义不明的“完善OAuth”。

## 28.3 Side Effect Check

本地配置/迁移/cache/日志/导出都有边界。清库、down -v、关闭鉴权、共享JWT_SECRET、后台密码登录不允许进入执行计划。

## 28.4 State Authority Check

Backend JWT payload不代替Snapshot；ENV不代替用户OAuth授权；本地缓存不代表上游全量；测试文案不代替Evidence。

## 28.5 Failure-path Check

§23每个注入点分配到具体测试；回滚区分本地原子事务和不能撤销的上游登录/Token轮换。

# 29. `.plan.md` 输出标准

```yaml
id: TODO-001
requirement_refs: [REQ-BOUNDARY-001]
acceptance_refs: [A-001, A-002]
files_or_symbols: [app/runtime.py, app/integrations/account_login/client.py]
implementation_goal: 固定唯一Backend登录HTTP路径，阻断其余路径
preconditions: 已批准PRD及固定源码SHA
state_transition: Runtime不再构造旧Backend身份适配器
side_effect_scope: 本项目源码和测试，不修改Backend服务
failure_cases: [重定向, 禁止路径, 会话到期]
verification: 含网络计数Oracle的单元及集成测试
commit_policy: post_review
status: planned
evidence: []
```

status为planned/implemented/verified/blocked；verified须有AC回执。以上是格式示例，不是已开始执行。

# 30. Code Review Contract

顺序：范围 → 旧Backend全路径清除 → 身份/角色/SOT → ENV唯一writer → OAuth owner/公司/Token域 → 分页/样本 → 有限重试/暂停 → 副作用/回滚 → AC/Evidence → 质量。

| 当前位置 | 改动类型 | 判断 |
|---|---|---|
| app/runtime.py | 替换 | 注入AccountLoginClient/LocalIdentityService，不构造旧BackendClient |
| app/integrations/nodeskclaw_backend/client.py | 退出运行 | 无运行入口导入调用；禁止路径只能出现在负向测试/文档 |
| core/config.py、cli.py | 修改 | 新ENV校验/apply；旧服务凭据不使用 |
| auth_service.py、api/deps.py | 修改 | 外部登录转本地Session；请求/Worker本地核验 |
| admin/portal/connection/maintenance/event调用点 | 修改或关闭 | 无隐式resolve/search；本scope外入口关闭 |
| callbacks/router.py、connection_service.py | 修改 | 无Portal前置，company待核验与本地确认 |
| query_service.py、meeting_service.py | 修改 | USER_RECORDINGS、全部页、provider ID映射、错误分类 |
| content_service.py、job_service.py、worker.py | 修改 | 会话时效、暂停恢复、PARTIAL/READY、有限重试 |
| models + alembic | 新增/迁移 | 本地身份/Session/结果/ENV Projection及唯一索引 |
| integration-kit、scripts、tests/live | 修改 | 新登录及OAuth-only Required集合 |
| Dockerfile、Compose、Nginx、README | 修改 | 冻结构建、独立部署、身份源一致 |
| 极简结果页 | 新增 | 无Token展示，不形成新会议平台 |

# 31. PRD Quality Gate

- [x] 唯一目标和不涉及AK/SK/STS/创建的范围已定义。
- [x] 三个禁止端点与唯一登录合同已定义。
- [x] 登录响应映射、Session及停用时效已定义，未包含真实Token。
- [x] ENV命名、公司审批、漂移和所有者已定义。
- [x] 状态、事务、hash、失败恢复已定义。
- [x] 每个需求有正负验收、Test和Oracle。
- [x] Synthetic/Golden与单通道门禁已分开。
- [ ] PRD负责人审批完成并变更APPROVED_FOR_PLAN。
- [ ] 实施代码及离线完整回归完成。
- [ ] 指定服务器真实OAuth数据提取执行完成。

勾选只表示文档合同存在，不表示功能实现或线上通过。

# 32. PRD 禁止写法

| 不可接受 | 本合同要求 |
|---|---|
| 前端说登录成功就信任 | 网关直接登录、白名单校验、短期本地会话 |
| 放.env即可，无需改代码 | Settings消费、env-apply、用户OAuth确认、实际读取 |
| 后台还可以resolve | 全路径禁止并举证0请求 |
| 连接ACTIVE即数据下载成功 | 真实sample、完整转写/纪要文件、摘要 |
| 无数据就是无会议 | 范围/权限/空结果分别记录；sample未命中不PASS |
| 先关闭权限再联调 | 本地owner/client/Tencent权限交集 |
| 不查询账号状态但实时停用 | 有限快照窗口与本地撤销，不推断外部实时变化 |

# 33. 推荐 ID 体系

本文使用REQ-<DOMAIN>-<NNN>、INV-NNN、A-NNN、TEST-A-NNN、EVID-A-NNN。以§10/20/27为准。修改保留ID，废弃需求标SUPERSEDED并关联新项，不复用不同语义。

# 34. PRD 最小完整结构

保留附件0—36章。目标/背景/范围§2—6；状态§7—8；Schema§9；需求§10；副作用/所有者/hash/事务/冲突/迁移§11—16；外部/安全/观测§17—19；验收/矩阵/负向/故障/证据§20—24；发布/真实Consumer§25—26；追踪/计划/审核§27—31；DoD§35。

# 35. Definition of Done

设计准入：审批身份时效、HTTP传输边界、公司允许列表、只读范围及迁移，状态APPROVED_FOR_PLAN，结构追踪无缺口。

实现完成：仅account-login可调用；三个禁止路径发送0；腾讯应用从.env初始化；无Portal/旧身份桥前置；本地权限有效；OAuth/读取/导出有代码与离线AC；旧模式无旁路。

联调完成：指定服务器出口获准、HTTPS callback有效；真实A登录/腾讯确认；内部客户端取得sample完整转写和元宝纪要，私有文件摘要匹配；B不能读A；Required证据齐全、报告退出0。

不纳入本轮：AK/SK、STS、企业全量、创建、媒体批量、MCP、OA、事件投递。标NOT_APPLICABLE_TO_SCOPE，不声称已验证。

# 36. 最终原则

身份链路只保留一次真实账号登录入口及本地会话，三个旧身份接口不再是任何流程前置。

腾讯企业ID、AppID、Secret从.env生效；账号密码不长期放.env；Backend令牌不替代Tencent OAuth。仅本人明确授权的连接可读获准资源。

终点是内部系统拿到真实会议数据并形成完整文件，不是服务启动、ACTIVE、HTTP200、脚本退出0或测试文件存在。未执行、缺证据的项保留BLOCKED/NOT_RUN。
