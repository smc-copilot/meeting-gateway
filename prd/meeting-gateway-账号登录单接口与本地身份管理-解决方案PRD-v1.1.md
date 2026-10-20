---
title: "meeting-gateway 账号登录单接口与本地身份管理解决方案 PRD"
prd_id: "PRD-MEETING-IDENTITY-LOGIN-ONLY"
version: "1.1.0"
status: "REVIEW"
template_version: "1.0"
product: "meeting-gateway"
repository: "https://github.com/smc-copilot/meeting-gateway"
branch: "master"
baseline_commit: "79e22d08b623a4f7816db05af631a463fe14348b"
target_release: "identity-login-only-1.1"
created_at: "2026-10-17"
updated_at: "2026-10-17"
change_type: [BROWNFIELD_CHANGE, ARCHITECTURE_CHANGE, INTEGRATION, MIGRATION]
implementation_status: "NOT_IMPLEMENTED_BY_THIS_DOCUMENT"
verification_status: "DOCUMENT_STRUCTURE_CHECK_ONLY"
---

# meeting-gateway 账号登录单接口与本地身份管理解决方案 PRD

**交付范围：改造既有网关的身份来源，不重建会议业务平台，不新增上游成员接口。**

用户已经明确禁止调用三条身份接口，只允许账号登录。本稿定义改造后的接口、配置、本地身份事实源、权限、会话、迁移和验收。文中的新接口与新配置是本次需求设计，不是当前仓库已实现的能力。源码检查基线为 `79e22d08b623a4f7816db05af631a463fe14348b`。未访问用户提供的内网登录地址，未使用对话中提供的令牌，也未在目标服务器执行部署或测试。

# 0. PRD 使用原则

## 0.1 本轮唯一约束

身份服务的 HTTP 出站集合仅允许：

```text
POST http://192.168.102.247:4510/api/v1/auth/account-login
```

以下三条在 API、Worker、OAuth、MCP、诊断、健康检查、脚本中均禁止调用：

```text
GET  /api/v1/auth/meeting-context
POST /api/v1/internal/meeting/principals/resolve
POST /api/v1/internal/meeting/principals/search
```

“只允许账号登录”同时排除对该身份服务的 `/health`、`/auth/me`、`/auth/refresh`、其他成员接口及探测请求；不是保留三条禁用接口的其他等价实现。上述限制针对**内部身份服务**，不禁止腾讯会议自身的 OAuth 刷新、STS、会议 API，也不禁止网关本地的令牌接口。

## 0.2 事实与设计标记

- **[用户要求]**：本轮输入中明确给出的限制、地址和响应字段。
- **[代码事实]**：固定提交中的实际实现，以第17章来源为准。
- **[本次设计]**：本稿提出的改造合同，评审后才能实施。
- **[验证边界]**：未获得现场接口、账号状态或执行证据的部分，不标记为已通过。

规范性 MUST / MUST NOT 集中在第10章的可追踪条款；其引用的表、公式、状态机和契约构成同一需求。未定义的决策归入 `SPEC_SEMANTIC_GAP`，阻断计划，不由开发人员补猜。

## 0.3 身份材料边界

用户贴出的登录结果仅用来确认响应结构。文档和测试不复制真实 access_token、refresh_token、姓名、邮箱或密码；静态样本用脱敏值。客户端上传的登录结果或解码后的 JWT 不属于可信身份事实源。

# 1. 文档元数据

| 字段 | 值 |
|---|---|
| Owner | meeting-gateway 项目负责人（职能角色，不虚构具体审批人） |
| Reviewers | 网关开发、内部系统负责人、部署运维、企业安全责任人 |
| Golden consumer | 指定白名单服务器上的网关、integration-kit、真实内部系统调用方 |
| 当前部署目录 | `/data/projects/meeting-meeting` |
| 联调工具目录 | `/data/projects/meeting-integration-kit` |
| 实施形态 | Python/FastAPI 独立服务增量改造；保留 PostgreSQL、Worker 和腾讯适配层 |
| 上游唯一身份入口 | `POST http://192.168.102.247:4510/api/v1/auth/account-login` |
| 原PRD替代范围 | 替代 v1.0 中 Backend 专用身份接口、实时成员解析、上游JWT兑换和安装身份桥的要求；不替代腾讯会议业务边界 |
| 文档状态 | REVIEW；不表示 APPROVED_FOR_PLAN、IMPLEMENTED 或 VERIFIED |
| 模板输入 | `需求PRD工程模板.md`，SHA-256：`b00234e6d103b2c102cbcc7b02fbcd961e71b0ce784ee736ead592c301e35eff` |

# 2. 一句话目标

让内部系统和运维人员在配置好网关组件标识、组织标识及唯一账号登录地址后，通过 meeting-gateway 完成账号登录、获得本地受控身份和令牌、调用腾讯会议相关服务，同时保证所有其他上游身份接口的调用次数为零，且身份、腾讯账号映射和会议权限不因改造而混为一项。

# 3. 背景与问题定义

## 3.1 Current State

| 代码事实 | 定位 | 影响 |
|---|---|---|
| `BackendClient.context/resolve/search` 直接调用三条被禁接口，`ready` 调用上游 `/health` | `app/integrations/nodeskclaw_backend/client.py` [S02] | 只改登录路由仍有多条违规出站 |
| `Runtime` 默认构造 `BackendClient` 并持有 `backend` | `app/runtime.py` [S03] | 所有运行进程仍装配旧依赖 |
| `MemberContext` 要求 `org_id/user_id/member_id` | `app/core/types.py` [S04] | 用户登录样本没有 `member_id`，不能原样替换 |
| 管理员入口、业务令牌、同意授权、令牌刷新会解析外部员工 | `AuthService` [S05] | 请求、授权和会话都要改 |
| `AdminService.human/bootstrap` 使用外部身份及 `member_role` | [S07] | 仅替换 URL 会使初始化与角色来源错误 |
| 腾讯连接和 AK/SK 调用前也会核验外部员工 | [S08][S09] | 会议读写、STS 和后台维护存在隐藏依赖 |
| 生产配置强制要求 `BACKEND_SERVICE_TOKEN` | [S06] | 新模式仍可能因无旧服务凭据启动失败 |
| 健康检查读取 Backend `/health` | [S13] | 即使没有业务请求也会违规调用 |

## 3.2 用户提供的登录信息能证明什么

输入中的 `data.user` 含 `id`、`current_org_id`、`portal_org_role`、`role`、`is_active`、`is_task_admin`、`must_change_password`，以及显示资料；`data` 含 `expires_in` 和两种令牌。它**没有**提供组织成员 `member_id`、部门树、完整员工目录或组件ID。

- 响应中 `role=user` 与 `portal_org_role=admin` 是两个不同字段；不能按第一个字段把组织管理员误判为普通组织成员。
- `is_task_admin=true` 不等于具有会议管理、正文或下载权限。
- `current_org_id` 是组织标识，不是腾讯 APPID、SDKID，也不是组件ID。
- 当前提供的成功响应不足以证明所有失败码、账号停用同步规则、现场运行 SHA 或请求上限。请求体 `{account,password}` 有历史上游 Schema 参考 [S21]，现场兼容性由第26章只通过 account-login 的实测确认。

## 3.3 Problem / Impact

可验证问题：当前网关在登录以外也会访问被禁止的身份接口；现有身份结构依赖登录响应没有提供的成员标识；直接接收上游JWT但不验证来源会引入伪造身份路径。

业务影响：指定服务器联调仍依赖额外身份桥。工程影响：修改范围跨 API、Worker、MCP 和配置。安全影响：删除外部校验后若没有本地可信会话与撤销机制，原权限边界会失效。运维影响：不得继续让 Hermes 安装专用成员接口或在 `.env` 伪造一名公共管理员。交付影响：文档、脚本和证据规则要同步切换，不能仅修改服务代码。

# 4. Scope

## 4.1 In Scope

| Scope ID | 范围 | Requirement |
|---|---|---|
| SCOPE-001 | 身份出站只保留账号登录 | REQ-API-001 |
| SCOPE-002 | .env 组件/组织/登录配置与一致性 | REQ-CONFIG-001 |
| SCOPE-003 | 登录请求、响应校验与资料归一化 | REQ-API-002、REQ-IDENTITY-001 |
| SCOPE-004 | 本地会话、交换、REST/MCP授权 | REQ-AUTH-001、REQ-AUTH-002 |
| SCOPE-005 | 管理员初始化、本地停用、成员查询 | REQ-SEC-001、REQ-DATA-001 |
| SCOPE-006 | Worker/腾讯连接使用本地身份 | REQ-RUNTIME-001 |
| SCOPE-007 | 事务、旧成员映射和凭据迁移 | REQ-TXN-001、REQ-MIGRATE-001 |
| SCOPE-008 | 凭据保护、HTTP例外与登录限流 | REQ-SEC-002、REQ-SEC-003 |
| SCOPE-009 | 健康诊断、可选登录视图、调用工具 | REQ-CHECK-001、REQ-UI-001、REQ-INTEGRATION-001 |
| SCOPE-010 | 零违规调用证据、回归、部署、真实联调 | REQ-EVID-001、REQ-REGRESSION-001、REQ-CMD-001、REQ-GOLDEN-001 |

## 4.2 Out of Scope

| Non-goal | 确切边界 |
|---|---|
| NON-GOAL-001 | 不创建或修改上游登录、成员、组织接口；不安装 `meeting_identity.py` |
| NON-GOAL-002 | 不读取上游数据库，不获取 Backend JWT 签名密钥，不借用管理员账号代替所有员工 |
| NON-GOAL-003 | 不实现上游找回密码、改密、短信、全员同步、跨组织切换或跨组织兜底 |
| NON-GOAL-004 | 不把 OAuth/AKSK 应用ID、员工ID、组织ID合并为同一配置 |
| NON-GOAL-005 | 不新增自动代他人创建、未批准SERVICE创建、全企业源查询能力；既有拒绝边界保持 |
| NON-GOAL-006 | 不因只登录就宣称具备远端实时停用检测；不伪造 `/resolve` 的本地固定返回值 |
| NON-GOAL-007 | 不重做会议工作台、OA审批、ASR、基础纪要或Hermes用户系统 |

## 4.3 Architecture Boundary

| Domain | Owner | Input | Output | 不负责 |
|---|---|---|---|---|
| 身份认证 | AccountLoginClient | 用户主动提交账号密码 | 经校验的单次登录观察 | 后台密码保管、成员查询 |
| 本地身份与会话 | IdentityService | 登录观察、组件/组织配置 | LocalMember、IdentitySession | 上游实时员工状态 |
| 会议权限 | PermissionService | 当前本地主体、ACL、委托 | 允许/拒绝 | 认证密码 |
| 腾讯连接 | ConnectionService/TencentClient | 本地身份映射、腾讯凭据 | 会议资源、授权状态 | 内部组织身份认证 |
| 内部系统 | 内部应用 | 用户输入、网关令牌 | 业务界面、流程 | 腾讯密钥管理 |
| 部署与证据 | 运维/integration-kit | 受控配置和真实账号 | 配置、回执、报告 | 修改判定标准使结果变绿 |

# 5. Terminology / Domain Model

| 术语 | 唯一定义 |
|---|---|
| 组件ID | `MEETING_COMPONENT_ID`，本次设计的网关逻辑实例/数据归属标识；同一API/Worker集群取同一值 |
| 组织ID | `MEETING_ORG_ID`，本次设计的单组织数据隔离标识；和登录结果 `current_org_id` 比较 |
| 外部用户ID | account-login 返回的 `data.user.id`；不用姓名、邮箱或用户名作为唯一身份 |
| 本地成员ID | 网关持久化的 `LocalMember.id`；不是上游 OrgMembership.id，除非经过显式旧映射承接 |
| 登录观察 | 网关服务端直接调用固定上游取得的白名单字段及接收时间，不包含密码和上游原始Token |
| 本地登录会话 | `ms_` 开头的随机不透明票据；只由网关签发和查表核验 |
| 业务令牌 | 既有 `mt_` 令牌，绑定内部客户端、主体和REST或MCP受众 |
| 身份租期 | 从这次成功登录到固定到期时间的证明区间；请求/刷新不延长它 |
| 本地停用 | 网关管理员设置的状态；优先于登录结果，不被下一次成功登录自动覆盖 |
| 登录角色 | 从 `portal_org_role` 归一化；不直接生成会议正文/创建/下载授权 |
| 远端状态未知 | 登录后无法得知账号状态是否改变；不以本地缓存冒充在线核验 |
| 实现 / 验证 | 实现表示代码存在；验证表示对应Acceptance有真实执行Evidence |

**术语决策：**用户原文为“组件 ID”。本稿不把它擅自改写成“组织 ID”，而是分开配置二者。用户样本支持组织ID的来源，但未提供平台组件ID字段。本稿的组件ID为新提出的本地配置，不声称是上游返回或平台分配的值。

# 6. System Context

## 6.1 Context Diagram

```text
内部系统/运维人员
  │ HTTPS：账号密码，仅用户主动登录时
  ▼
Meeting /api/v1/auth/account-login（新增本地路由）
  │ 唯一身份服务出站：POST account-login
  ▼
192.168.102.247:4510 ──返回user──> 响应校验/组织校验
                                   │
                          本地成员＋短期会话(ms_)
                                   │
                 客户端凭据＋ms_ → 业务令牌(mt_)
                                   │
                 REST / MCP → 本地权限 → 腾讯会议
                                   │
                      Worker、回调、下载、审计

API/Worker/健康检查 ──X──> meeting-context / resolve / search / auth/me / auth/refresh / health（上游）
```

## 6.2 System Boundary

可信输入：受控 `.env`、经过固定上游成功交换且校验的白名单字段、网关已保存并验证的令牌/授权。非可信输入：客户端上传 user JSON、旧Backend JWT、账号显示名、请求中的 org_id/member_id、URL、缓存命中标签。

这仍是对**现有账号登录服务**的依赖，不宣称彻底不依赖任何上游。区别在于：登录以外的身份判断全部落到网关本地，不调用额外接口。

# 7. Authoritative State / Source of Truth

| State | 分类 | Authoritative? | Writer | Reader | 自动覆盖 |
|---|---|---:|---|---|---|
| `.env`组件/组织/固定URL | DESIRED_STATE | 是，部署目标 | 运维 | 配置加载器 | 否 |
| `IdentityDeployment` | LAST_APPLIED_STATE | 是，已应用命名空间/epoch | 启动检查/迁移命令 | 所有进程 | 仅受控迁移 |
| 成功登录的白名单字段 | OBSERVED_STATE | 仅代表登录时刻 | AccountLoginClient | IdentityService | 新观察可追加，旧观察不可改 |
| `LocalMember` | RESOLVED_STATE | 是，网关成员与本地停用 | IdentityService/管理员 | 所有业务 | 外部资料可更新；local_enabled不覆盖 |
| `IdentitySession` | RUNTIME_STATE | 是，ms_有效性及固定到期 | 登录/撤销服务 | 管理、交换、OAuth | 不延长到期 |
| `AccessToken/AgentGrant/AccessGrant` | RUNTIME_STATE | 是，客户端与资源权利 | 本地授权服务 | REST/MCP/Worker | 不由登录角色生成全量权利 |
| 腾讯凭据与绑定 | RUNTIME_STATE | 是，腾讯连接状态 | 原连接服务 | 腾讯适配器 | 本轮身份迁移不覆盖密文 |
| 联调回执 | EVIDENCE_STATE | 只证明执行过的断言 | 测试/工具 | 发布门禁 | 不回写成权限 |

有效权限 = 本地身份/主体有效 ∩ 会话或SERVICE批准有效 ∩ 客户端范围 ∩ 资源范围 ∩ 委托范围 ∩ 腾讯侧允许。组件ID和组织ID都不是授权凭据。

# 8. State Machine

## 8.1 登录尝试

```text
RECEIVED → VALIDATED → UPSTREAM_REQUESTED → UPSTREAM_VERIFIED → COMMITTED → ISSUED
       ↘ REJECTED       ↘ FAILED/TIMEOUT       ↘ CONTRACT_REJECTED
```

尝试对象由 `attempt_id` 标识。请求未校验前无上游HTTP；一个attempt最多一次登录POST，不自动重发密码。校验顺序固定为：请求/限流 → HTTP与响应核心类型 → needs_org_setup/current_org_id存在性 → 组织匹配 → 已知成员本地禁用 → active/强制改密 → 角色和资料投影 → 本地提交。`COMMITTED` 前不得把ms_交给调用方；提交后响应丢失不撤销已经提交的数据，也不重放上游登录。用户可主动重新登录建立新会话。

## 8.2 本地成员

| Before | Event / 前置条件 | After | 持久化与恢复 |
|---|---|---|---|
| 不存在 | 成功登录、组织匹配、状态合格 | ACTIVE | 创建新LocalMember |
| LEGACY_UNVERIFIED | 完成映射且首次真实登录 | ACTIVE | 保留既有member_id与授权引用 |
| ACTIVE | 当前登录显示停用/强制改密/角色变化 | STATUS_REJECTED或更新后的ACTIVE | 增加identity_version并撤销旧会话；角色变化可签发新会话 |
| STATUS_REJECTED | 更晚的真实登录返回合格且local_enabled=true | ACTIVE | 新观察、新会话；旧会话不复活 |
| ACTIVE | 本地管理员停用 | LOCAL_DISABLED | 撤销全部会话和员工/智能体派生令牌 |
| LOCAL_DISABLED | 再次上游登录成功 | LOCAL_DISABLED | 拒绝登录，本地禁用优先 |
| LOCAL_DISABLED | 其他有效管理员明确恢复 | LEGACY_UNVERIFIED | 下一次真实登录后才能ACTIVE |

用户名/邮箱修改只更新展示字段，不能创建第二个成员。账号错误或上游超时不能将匹配名字的本地成员禁用。

## 8.3 会话、派生令牌和作业

`ACTIVE → EXPIRED / REVOKED` 为终止转移。重新登录创建新会话，不复活旧会话。令牌刷新可以轮换mt_，但派生令牌到期不超过父会话固定到期。

员工/智能体作业执行前和分页边界校验父会话；已过期作业写 `FAILED + IDENTITY_REAUTH_REQUIRED`，不无限重试、不后台自动登录。CREATE发出前过期：写失败且腾讯写请求数为0；已发出时不倒改结果，按既有成功/失败/OUTCOME_UNKNOWN日志保存。

SERVICE任务不伪装MEMBER，不读取用户密码，也不靠假会话维持。它只按已有的本地客户端、采集批准、绑定操作者、本地停用和腾讯权限执行。**只登录模式不能检测这些批准期间发生的所有远端员工停用；本地撤销及时生效，远端拒绝由腾讯或下一次主动登录观察。**本轮不新开放当前被禁的SERVICE创建路径。

# 9. Data / Schema Contract

## 9.1 Schema Rule

网关入参默认 `additionalProperties=false`。上游响应允许额外字段，以免用户样本中的扩展资料阻断登录，但只投影第9.3节字段；额外字段不落原始日志、不形成权限。核心字段缺失或类型错误拒绝，不用Pydantic隐式把字符串 `"true"` 转布尔、把 `null` 转默认活跃。

## 9.2 配置 Schema：meeting.identity.config/1

以下为**新增设计**，不是当前配置已经生效。

```dotenv
IDENTITY_MODE=account_login
ACCOUNT_LOGIN_URL=http://192.168.102.247:4510/api/v1/auth/account-login
MEETING_COMPONENT_ID=meeting-gateway
MEETING_ORG_ID=2be7c618-326d-4a73-91ea-1cfda10f7073
MEETING_BOOTSTRAP_ADMIN_USER_IDS=["55576b5f-5be6-4a20-aca8-5b5526adf18a"]
AUTH_SESSION_TTL_SECONDS=900
AUTH_ADMIN_FRESH_SECONDS=300
ACCOUNT_LOGIN_ALLOW_PRIVATE_HTTP=true
# 以下仍沿用现有安全配置，不在本PRD填写真实密钥
# DATABASE_URL、KEYRING_JSON、ACTIVE_KEY_ID、PUBLIC_BASE_URL、ALLOWED_HOSTS
```

示例组织ID和初始化用户ID来自用户输入；组件ID `meeting-gateway` 是本稿示例。每个部署实例按审批后的值设置。腾讯企业ID、SDKID及应用Secret保持原有独立配置路径，不从这些ID推导。

| Field | Type / Required | Default | Authority / Meaning |
|---|---|---|---|
| IDENTITY_MODE | enum / 是 | account_login | 本版仅允许此值，无旧模式fallback |
| ACCOUNT_LOGIN_URL | string / 是 | 用户指定精确URL | 本版规范化后等于固定URL；禁 query、fragment、userinfo、其他path、其他host |
| MEETING_COMPONENT_ID | ASCII `[a-z][a-z0-9-]{2,63}` / 是 | 无 | 一个逻辑网关集群的固定标识，不是Pod ID |
| MEETING_ORG_ID | UUID string / 是 | 无 | 单组织；与有效登录响应的current_org_id严格匹配 |
| MEETING_BOOTSTRAP_ADMIN_USER_IDS | UUID array / 是 | [] | 显式允许初始化管理员的外部用户ID，空数组禁止首次bootstrap |
| AUTH_SESSION_TTL_SECONDS | int60..3600 / 是 | 900 | 身份租期上限，不采用上游86400直接放大 |
| AUTH_ADMIN_FRESH_SECONDS | int30..300 / 是 | 300 | 高权限配置与bootstrap要求登录在此区间内；不得大于sessionTTL |
| ACCOUNT_LOGIN_ALLOW_PRIVATE_HTTP | bool / 是 | false | 指定HTTP内网地址需显式true；不扩展为任意HTTP放行 |
| NODESKCLAW_BACKEND_URL / BACKEND_SERVICE_TOKEN | 废弃 | 不读取 | 非空残留时启动拒绝 `LEGACY_IDENTITY_CONFIG_FORBIDDEN`；迁移后删除 |

上述UUID统一解析为小写标准带连字符形式。首次应用后组件/组织组合持久化，后续改 `.env` 不得把原数据库自动切到另一个组织。

## 9.3 登录请求与响应：meeting.account-login/1

**新增本地入口：**`POST /api/v1/auth/account-login`。只收：

```json
{"account":"<用户输入账号>","password":"<用户输入密码>"}
```

两字段为1..200字符；account不得全空白；密码不trim、不规范化、不哈希后替换。请求总长限制16 KiB。禁止客户端同时提交user、role、member_id、org_id、component_id、source_token、上游URL。网关主动发往固定上游，同一路径但不同主机，不构成循环调用。

| 上游字段 | 校验及用途 |
|---|---|
| HTTP status、`code` | HTTP200且code为严格整数0；不是false或字符串0 |
| `error_code / message_key` | 成功时仅允许null或未提供；HTTP200、code=0却给出非空错误字段时按合同错误拒绝 |
| `data.user.id` | 非空合法UUID，唯一外部用户ID |
| `data.user.current_org_id` | 非空合法UUID，等于.env组织；空、不匹配均拒绝 |
| `data.user.is_active` | 严格bool，必须true |
| `data.user.must_change_password` | 严格bool，必须false |
| `data.needs_org_setup` | 严格bool，必须false |
| `data.user.portal_org_role` | admin/operator/member原值映射；null/缺失/未知字符串降为member并记ROLE_UNRECOGNIZED；非字符串非null拒绝 |
| `data.user.role` | 可保留为展示资料，不参与会议授权 |
| `data.user.is_super_admin / is_task_admin` | 只记录非授权展示标记；不授会议权，不跳组织校验 |
| name/username/email | 可选显示字段，按Schema长度128/200/320限制；缺省空或null，不用于匹配身份 |
| `data.expires_in` | 严格整数1..86400，作为租期上界之一；缺失/0/负数/布尔拒绝 |
| `data.token_type` | string，大小写不敏感等于bearer |
| `data.access_token / refresh_token` | 仅验证为非空string且各≤16384字符；不解码作认证，不持久化、不转交调用方、不调用上游刷新 |

上游响应最多256 KiB；超限、JSON重复键、类型错误、HTML、畸形JSON均拒绝。这里不保存上游完整响应；不能将“从用户聊天贴出的响应”写入数据库代替实际交换。

本地成功响应：

```json
{
  "code": 0,
  "error_code": null,
  "message_key": null,
  "message": "success",
  "data": {
    "session_token": "<网关生成ms_票据，仅成功响应返回一次>",
    "token_type": "bearer",
    "expires_in": 900,
    "identity_mode": "account_login",
    "component_id": "meeting-gateway",
    "org_id": "<配置组织ID>",
    "user": {
      "user_id": "<上游user.id>",
      "member_id": "<本地成员ID>",
      "name": "<白名单显示资料>",
      "member_role": "admin"
    }
  }
}
```

不返回上游access_token/refresh_token；`expires_in`为实际剩余整数秒，例子900不是固定回填值。

## 9.4 本地表：meeting.identity.tables/1

| Table / Key | 必需字段及默认 | 作用与生命周期 |
|---|---|---|
| IdentityDeployment / component_id | org_id、issuer_id=`account-login-v1`、namespace_version=1、auth_mode_epoch、applied_config_digest | 环境绑定、API/Worker一致性；只由迁移/首次配置写 |
| LocalMember / id | component_id、org_id、issuer_id、external_user_id、source、local_enabled=true、state、identity_version=1、last_applied_attempt_seq、last_verified_at、profile_json | 持久目录； `(component_id,org_id,issuer_id,external_user_id)` 活跃行部分唯一索引 |
| LoginObservation / id | member_id、attempt_seq、received_at、normalized_role、observed_flags、accepted_for_session、source_expires_in、valid_until、projection_digest | 最小化、不可变观察；不存密码/上游令牌 |
| IdentitySession / id | token_hash、member_id、observation_id、component_id、org_id、issued_at、expires_at、revoked_at、identity_version、auth_mode_epoch | 哈希唯一；会话寿命固定；软删除或到期不能复活 |
| AccessToken（增量） | identity_session_id、identity_version、auth_mode_epoch | MEMBER/AGENT为非空；SERVICE允许空；mt_/mr_继承父租期 |
| Principal（增量） | identity_session_id、identity_expires_at、identity_version、auth_mode_epoch | 只由服务器构造，JSON入参不能覆盖 |
| IdentityMigration / id | from_epoch、to_epoch、manifest_digest、state、pre_snapshot_digest、report_path | 迁移账本；不保存密钥 |

所有新增业务行沿用软删除与UTC时间。现有数据库模型的行所有权保留。相关索引/列通过Alembic自动生成并Review；不手写revision ID。新表不是第二套密码账号库，而是可信登录结果的本地投影及会话状态。

### 9.4.1 字段类型与缺省值

新表主键id为标准UUID字符串；组件ID按第9.2章；org_id、external_user_id标准UUID；issuer_id固定account-login-v1；identity_version/auth_mode_epoch为大于等于1的64位整数。attempt_seq为数据库分配的大于0的64位整数，允许失败留下序号空洞。last_applied_attempt_seq初始0，仅提交接受观察时更新。所有时间为带时区UTC，未观察的last_verified_at为null。

LocalMember.source为ACCOUNT_LOGIN或LEGACY_MAPPING；state为LEGACY_UNVERIFIED、ACTIVE、STATUS_REJECTED、LOCAL_DISABLED。local_enabled默认true，但LEGACY_UNVERIFIED不能通过身份检查；源状态与本地禁用同时不合格时以LOCAL_DISABLED拒绝。profile_json只保存已列明且有界的name/username/email及展示角色标记，不接受任意扩展字段。

LoginObservation.accepted_for_session为严格bool。有效登录true；有对应旧LocalMember且已核实返回停用/强制改密时可追加false观察并撤销；该观察valid_until=received_at，不签会话。未登记用户被拒绝时只记脱敏attempt，不为失败登录创建可信成员。state或role返回有问题但身份核心字段无法验证时，不修改既有成员。

IdentitySession状态由revoked_at和expires_at派生：revoked_at非空优先REVOKED；否则now>=expires_at为EXPIRED；否则ACTIVE。当前LocalMember非ACTIVE、local_enabled=false、identity_version不符或auth_mode_epoch不符时，即使会话行未过期也拒绝。身份表中的局部展示角色不代替AccessGrant。

所有API/Worker副本共享同一PostgreSQL身份状态，本版不使用跨请求的有效会话正缓存。原Principal.is_super_admin在此模式固定为false，上游同名字段仅作为profile展示资料，不能参与任何超级管理员旁路。

## 9.5 本地接口与令牌兼容合同

| 本地HTTP入口 | 改造后输入/输出 | 身份网络副作用 |
|---|---|---|
| POST `/api/v1/auth/account-login`（新增） | account/password→ms_与本地资料 | 恰好最多一次上游登录 |
| POST `/api/v1/auth/logout`（新增） | ms_→撤销当前本地会话和派生令牌 | 0；不是上游全局登出 |
| GET `/api/v1/auth/session`（新增） | ms_→当前本地会话/身份期限 | 0 |
| POST `/api/v1/auth/exchange`（改造） | 原client_id/client_secret/scopes/resource保留；subject_token改为ms_ | 0；旧Backend JWT拒绝 |
| GET/POST `/api/v1/admin/*`、`/api/v1/portal/*`（改造） | 用ms_构造管理/人工主体；保留各自权限 | 0；不要求部署Portal UI |
| GET `/api/v1/portal/members`（改造） | 仅查询本地已登录/已验证的成员 | 0；无上游全员目录 |
| POST `/api/v1/admin/members/{member_id}/disable`（新增） | 有权管理员+reason→本地禁用 | 0 |
| POST `/api/v1/admin/members/{member_id}/enable`（新增） | 有权管理员+reason→等待重新登录 | 0 |
| POST `/oauth/token`（保留） | 下游PKCE/refresh/client_credentials | 0身份HTTP；刷新不越父会话期限 |
| 业务REST与`/mcp`（保留） | 只接受正确受众的mt_；ms_不能直读正文 | 0身份HTTP；腾讯HTTP按原合同 |

本地登出与disable均对后续授权检查生效；正在发送的HTTP字节不能撤回。`ms_`不能调用普通会议业务；`mt_`不能冒充管理会话。`portal`内部布尔字段可暂留以兼容原服务调用，但它只能由本地会话验证生成，不代表必须使用前端Portal。

## 9.6 会话期限与角色公式

```text
identity_deadline = observation_received_at + min(upstream.expires_in, AUTH_SESSION_TTL_SECONDS)
session.expires_at = identity_deadline
access.expires_at = min(now + ACCESS_TOKEN_SECONDS, session.expires_at, agent_grant.expires_at[如有])
refresh.expires_at <= session.expires_at
```

新登录建立新的session；不得因profile更新、刷新mt_、调用成员查询或后台心跳延长旧session。管理员配置类请求还要求 `now - session.issued_at <= AUTH_ADMIN_FRESH_SECONDS`。

角色来源：只从portal_org_role归一化，不能在 `role/org_role/portal_org_role/is_task_admin` 之间“挑最高权限”。初始bootstrap还需要外部user.id在.env允许列表中；登录本身不创建业务ACL。

“最后有效本地管理员”的计数规则：同组件/组织内，LocalMember为ACTIVE且local_enabled=true，同时具有未过期、启用的ORG_APPROVED/MANAGE允许授权，覆盖meeting.acl.manage与meeting.application.manage且无对应DENY。计数不依赖管理员是否当前在线；要停用的成员仍在该集合且集合大小为1时拒绝。

非namespace参数变更只通过受控配置diff/apply更新applied_config_digest并重启进程；它不能自动延长任何已签发会话。缩短TTL只约束新登录，需立即终止旧会话时使用本地撤销流程。组件/组织/issuer变更始终阻断现库启动，不能按普通配置更新处理。

## 9.7 错误码扩展：meeting.identity.errors/1

现有 `reason + 数值error_code + message_key + code(HTTP语义) + data + trace_id` 结构保留；现有码710001..710041不重排 [S25]。新增如下稳定映射，message_key统一为 `errors.meeting.<reason的小写>`。

| Reason | 数值error_code | HTTP / 进程 | 语义 |
|---|---:|---|---|
| IDENTITY_CONFIG_INVALID | 710042 | 启动exit2 | 新配置缺失或类型错误 |
| LEGACY_IDENTITY_CONFIG_FORBIDDEN | 710043 | 启动exit2 | 旧身份配置仍非空 |
| IDENTITY_NAMESPACE_MISMATCH | 710044 | 启动exit2 / 409 | 组件/组织/issuer/epoch与库不一致 |
| IDENTITY_EGRESS_FORBIDDEN | 710045 | 503 | 试图访问非唯一允许地址；请求不发出 |
| ACCOUNT_LOGIN_REJECTED | 710046 | 401 | 上游401/403或HTTP200且code为非零整数；不转发账号存在性信息 |
| ACCOUNT_LOGIN_UNAVAILABLE | 710047 | 503 | 网络失败、超时、429/5xx；不自动重试 |
| ACCOUNT_LOGIN_CONTRACT_ERROR | 710048 | 502 | 畸形、超长或核心字段不符；3xx也不跟随 |
| ACCOUNT_ORG_MISMATCH | 710049 | 403 | 返回组织与配置组织不同 |
| ACCOUNT_ORG_REQUIRED | 710050 | 403 | 返回无组织或needs_org_setup=true |
| ACCOUNT_PASSWORD_CHANGE_REQUIRED | 710051 | 403 | 返回must_change_password=true |
| IDENTITY_REAUTH_REQUIRED | 710052 | 401 | 身份租期到期或旧Backend JWT作为凭据 |
| LOCAL_MEMBER_DISABLED | 710053 | 403 | 本地禁用优先 |
| LOCAL_MEMBER_NOT_ENROLLED | 710054 | 409 | 要绑定/选择的员工还没有本地可信登录 |
| IDENTITY_MIGRATION_REQUIRED | 710055 | 启动exit2 / 409 | 活跃旧引用缺少明确映射 |
| IDENTITY_MAPPING_CONFLICT | 710056 | 409 / 命令exit2 | 旧成员和外部用户不是一一映射 |
| ADMIN_REAUTH_REQUIRED | 710057 | 401 | 管理操作超过300秒新鲜度 |
| LAST_ADMIN_DISABLE_FORBIDDEN | 710058 | 409 | 不允许在线操作停用最后一个有效本地管理员 |
| IDENTITY_MODE_CHANGED | 710059 | 401 | 令牌来自旧auth_mode_epoch |
| EVIDENCE_INCOMPLETE | 710060 | 工具exit2 | 必需验收证据缺失 |
| SPEC_SEMANTIC_GAP | 710061 | 工具exit2 | 计划生成出现未定义决策 |
| IDENTITY_MIGRATION_UNCERTAIN | 710062 | 命令exit2 | 迁移提交结果需人工核对，不能再apply |

`is_active=false`仍使用MEMBER_INACTIVE/710018。非法本地请求使用INVALID_REQUEST/710017；本地限流使用RATE_LIMITED/710022。未知4xx（非401/403/429）归为ACCOUNT_LOGIN_CONTRACT_ERROR，不误报为用户名不存在。

# 10. Requirement Unit

## REQ-API-001 — 身份出站唯一入口与零违规调用

### Goal
避免将三条禁止接口藏在适配器、健康探测或后台任务中。

### Normative Requirement
- `REQ-API-001-N01`：MUST 将身份服务的HTTP请求限制为第0章固定的POST account-login，仅由用户主动登录调用。
- `REQ-API-001-N02`：MUST NOT 在API、Worker、MCP、OAuth、诊断、脚本、重试与健康检查中发出其他身份HTTP；禁用URL重定向、环境代理和替代接口兜底。

### Inputs
固定URL、账号密码、请求阶段；禁止客户端决定URL/HTTP方法。

### Preconditions
PRE-API-001-01：配置已通过校验；无隐式后台登录。

### Authoritative State
SOT：.env目标和IdentityDeployment；调用轨迹是Evidence。

### State Transition
请求校验→允许一次登录POST；任何其他目标→本地拒绝，不进入socket。

### Allowed Side Effects
ALLOW：固定地址登录网络、脱敏审计和限流计数。

### Forbidden Side Effects
DENY：三条禁止接口、上游/health、/me、refresh、路径变体、跨host重定向。

### Ownership Scope
FILE：登录适配器与运行时网络出口。
实施定位（目标，不表示已实现）：app/integrations/account_login/client.py（新增）；app/runtime.py；移除旧BackendClient运行时引用。

### Idempotency
登录不是幂等缓存；每个明确登录attempt最多一个POST；后台重复检查始终0请求。

### Failure Semantics
F-API-001-01：目标不符→IDENTITY_EGRESS_FORBIDDEN，0上游请求；超时→ACCOUNT_LOGIN_UNAVAILABLE，不重试。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-API-001-01：所有非登录请求不依赖身份服务器实时连通性；腾讯HTTP按独立适配器保留。

### Invariants
INV-API-001：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
ACCOUNT_LOGIN_UNAVAILABLE; IDENTITY_EGRESS_FORBIDDEN。数值与HTTP语义以第9.7章为准。

### Acceptance
A-API-001-01, A-API-001-02。

### Evidence
required test：tests/identity/test_api_001.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

## REQ-CONFIG-001 — 组件和组织配置替代身份桥配置

### Goal
组件/组织由部署确定，不为取得ID额外调用成员接口。

### Normative Requirement
- `REQ-CONFIG-001-N01`：MUST 实现第9.2章新增配置和命名空间绑定；API与Worker使用同一组件、组织和auth_mode_epoch。
- `REQ-CONFIG-001-N02`：MUST NOT 将所有员工固定为一个.env成员ID；不得把组件ID当组织ID或腾讯APPID；不得读取旧服务凭据fallback。

### Inputs
.env及数据库IdentityDeployment。

### Preconditions
PRE-CONFIG-001-01：部署已选择真实组织；密钥配置沿用现有存储加密。

### Authoritative State
SOT：.env为desired、数据库为last_applied。

### State Transition
首次匹配→建立配置记录；已有不匹配→拒绝启动。

### Allowed Side Effects
ALLOW：首次IdentityDeployment行、配置指纹、受控诊断。

### Forbidden Side Effects
DENY：启动自动换组织、自动覆盖密钥、填假后台服务Token。

### Ownership Scope
FIELD：身份配置；ROW：部署命名空间。
实施定位（目标，不表示已实现）：app/core/config.py；app/cli.py；.env.example；deploy/compose.yaml；app/models/identity.py（新增）。

### Idempotency
同配置重复启动不改namespace；异配置启动拒绝且业务行不变。

### Failure Semantics
F-CONFIG-001-01：缺失→IDENTITY_CONFIG_INVALID；旧配置残留→LEGACY_IDENTITY_CONFIG_FORBIDDEN；错namespace→IDENTITY_NAMESPACE_MISMATCH。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-CONFIG-001-01：无需BACKEND_SERVICE_TOKEN即可启动新模式，但数据库和加密密钥仍必需。

### Invariants
INV-CONFIG-001：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
IDENTITY_CONFIG_INVALID; IDENTITY_NAMESPACE_MISMATCH; LEGACY_IDENTITY_CONFIG_FORBIDDEN。数值与HTTP语义以第9.7章为准。

### Acceptance
A-CONFIG-001-01, A-CONFIG-001-02。

### Evidence
required test：tests/identity/test_config_001.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

## REQ-API-002 — 服务端账号登录与响应验真

### Goal
登录事实来自网关发出的请求，而非客户端提交的user JSON或JWT解码结果。

### Normative Requirement
- `REQ-API-002-N01`：MUST 实现第9.3章本地账号登录请求、固定上游交换、严格核心字段校验和白名单投影。
- `REQ-API-002-N02`：MUST NOT 接收客户端伪造的user/role/org信息作为认证结果；不把示例令牌写入配置；登录响应核心字段不允许隐式类型转换。

### Inputs
account/password；直接上游HTTP响应。

### Preconditions
PRE-API-002-01：请求≤16KiB；账号密码各1..200字符；URL已固定。

### Authoritative State
SOT：当前attempt直接HTTP结果；用户提供样本仅为Schema参考。

### State Transition
校验成功→持久化阶段；不合格→REJECTED且不签发会话。

### Allowed Side Effects
ALLOW：一次上游登录（可能修改上游last_login等），本地投影、限流和审计。

### Forbidden Side Effects
DENY：缓存密码、重放先前上游响应、从jwt.sub直接认定身份。

### Ownership Scope
REQUEST/ROW：登录观察与会话。
实施定位（目标，不表示已实现）：app/schemas/identity.py（新增）；app/api/identity.py（新增）；app/services/login_service.py（新增）。

### Idempotency
每次主动登录产生独立attempt；返回丢失后新登录不复用旧密码请求。

### Failure Semantics
F-API-002-01：字段不符→ACCOUNT_LOGIN_CONTRACT_ERROR；非零code→ACCOUNT_LOGIN_REJECTED；组织不符→ACCOUNT_ORG_MISMATCH。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-API-002-01：未通过响应验证的调用拿不到ms_或mt_；未知非核心字段不保存。

### Invariants
INV-API-002：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
ACCOUNT_LOGIN_CONTRACT_ERROR; ACCOUNT_LOGIN_REJECTED; ACCOUNT_ORG_MISMATCH。数值与HTTP语义以第9.7章为准。

### Acceptance
A-API-002-01, A-API-002-02。

### Evidence
required test：tests/identity/test_api_002.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

## REQ-IDENTITY-001 — 本地成员标识与字段归一化

### Goal
填补account-login不提供member_id的结构差异，同时保持多用户分离。

### Normative Requirement
- `REQ-IDENTITY-001-N01`：MUST 以组件、配置组织、固定issuer和返回user.id建立第13章规定的本地成员ID；已映射旧成员保留旧ID。
- `REQ-IDENTITY-001-N02`：MUST 按第9章从portal_org_role产生member_role，仅显示其他角色标记。
- `REQ-IDENTITY-001-N03`：MUST NOT 使用用户名/邮箱/姓名匹配旧权限，或执行user_id=member_id的默认替换；组织为空或不同不建立跨组织成员。

### Inputs
投影后的user.id/current_org_id/profile；可选已批准迁移映射。

### Preconditions
PRE-IDENTITY-001-01：合法登录；身份namespace已绑定。

### Authoritative State
SOT：LocalMember唯一键与IdentityMigration。

### State Transition
不存在→新ACTIVE；已存在→更新资料；映射冲突→拒绝。

### Allowed Side Effects
ALLOW：本地成员、观察和identity_version。

### Forbidden Side Effects
DENY：改写腾讯userid/open_id、吞掉org差异、按role全局管理员提权。

### Ownership Scope
ROW：LocalMember与观察。
实施定位（目标，不表示已实现）：app/core/types.py；app/models/identity.py；app/services/identity_service.py（新增）。

### Idempotency
同一user重复登录ID恒定；不同user永不共享ID；资料变化不换ID。

### Failure Semantics
F-IDENTITY-001-01：映射非一一对应→IDENTITY_MAPPING_CONFLICT；未知上游role→member；current_org_id=null→ACCOUNT_ORG_REQUIRED。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-IDENTITY-001-01：本地member_id可以继续被现有ACL引用；不冒称上游组织成员ID。

### Invariants
INV-IDENTITY-001：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
ACCOUNT_ORG_REQUIRED; IDENTITY_MAPPING_CONFLICT。数值与HTTP语义以第9.7章为准。

### Acceptance
A-IDENTITY-001-01, A-IDENTITY-001-02。

### Evidence
required test：tests/identity/test_identity_001.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

## REQ-AUTH-001 — 本地登录会话与固定身份租期

### Goal
只使用账号登录也能验证后续请求，不依赖上游JWT解析或无限缓存。

### Normative Requirement
- `REQ-AUTH-001-N01`：MUST 实现第8、9.6、13章的ms_会话、固定租期、哈希保存、到期/登出/禁用/epoch失效。
- `REQ-AUTH-001-N02`：MUST NOT 保存上游access/refresh_token用于后续认证或刷新，不存密码，不让refresh和后台续期延长父身份租期。

### Inputs
合法登录观察、32字节随机数、UTC时钟。

### Preconditions
PRE-AUTH-001-01：成员local_enabled且sessionTTL配置有效。

### Authoritative State
SOT：IdentitySession、LoginObservation、LocalMember。

### State Transition
成功提交→ACTIVE；到期/撤销→终态；新登录→新会话。

### Allowed Side Effects
ALLOW：会话哈希、审计、本地派生令牌撤销。

### Forbidden Side Effects
DENY：明文票据落库、永久登录、旧会话复活。

### Ownership Scope
ROW：会话与令牌族。
实施定位（目标，不表示已实现）：app/services/auth_service.py；app/models/identity.py；app/core/security.py。

### Idempotency
会话检查只读；登出重复请求不扩大范围，已撤销响应仍为200。

### Failure Semantics
F-AUTH-001-01：到期→IDENTITY_REAUTH_REQUIRED；本地禁用→LOCAL_MEMBER_DISABLED；旧epoch→IDENTITY_MODE_CHANGED。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-AUTH-001-01：过期上游观察不能作为新登录证明；外部状态只代表最近一次观察。

### Invariants
INV-AUTH-001：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
IDENTITY_MODE_CHANGED; IDENTITY_REAUTH_REQUIRED; LOCAL_MEMBER_DISABLED。数值与HTTP语义以第9.7章为准。

### Acceptance
A-AUTH-001-01, A-AUTH-001-02。

### Evidence
required test：tests/identity/test_auth_001.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

## REQ-AUTH-002 — 内部客户端、REST与MCP本地授权

### Goal
保留内部系统/员工/智能体三种身份边界，不增加上游调用。

### Normative Requirement
- `REQ-AUTH-002-N01`：MUST 保留客户端凭据、scope、audience、ACL交集和PKCE；exchange的subject_token只接受本地ms_。
- `REQ-AUTH-002-N02`：MUST 将管理/人工授权从Backend Bearer切换为本地ms_；AGENT绑定父会话与已有委托，逐调用本地核验。
- `REQ-AUTH-002-N03`：MUST NOT 接受仅有员工ID的调用；禁止ms_直读会议、mt_进入管理、REST令牌进入MCP或智能体自行批准创建。

### Inputs
ms_、客户端凭据、scopes/resource、现有PKCE请求。

### Preconditions
PRE-AUTH-002-01：本地有效会话；client和权限有效。

### Authoritative State
SOT：IdentitySession、AccessToken、Client、AgentGrant、AccessGrant。

### State Transition
ms_有效→签发绑定客户端mt_；撤销/到期→拒绝。

### Allowed Side Effects
ALLOW：本地令牌族/授权码、审计。

### Forbidden Side Effects
DENY：上游认证或成员网络、受众串用、客户端选择人类身份。

### Ownership Scope
ROW：下游授权。
实施定位（目标，不表示已实现）：app/authorization/router.py；app/api/deps.py；app/services/auth_service.py；app/mcp/server.py。

### Idempotency
鉴权只读；刷新使用原令牌族单次消费语义，重用撤销该族。

### Failure Semantics
F-AUTH-002-01：旧subject_token→IDENTITY_REAUTH_REQUIRED；受众错→AUDIENCE_MISMATCH；委托不足→PERMISSION_DENIED。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-AUTH-002-01：已保存的数据权限继续由同一PermissionService执行。

### Invariants
INV-AUTH-002：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
AUDIENCE_MISMATCH; IDENTITY_REAUTH_REQUIRED; PERMISSION_DENIED。数值与HTTP语义以第9.7章为准。

### Acceptance
A-AUTH-002-01, A-AUTH-002-02。

### Evidence
required test：tests/identity/test_auth_002.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

## REQ-SEC-001 — 初始管理员、本地禁用及权限保留

### Goal
取消远程成员解析后，仍有可执行的管理与撤权流程。

### Normative Requirement
- `REQ-SEC-001-N01`：MUST 仅在本地组织未初始化、登录角色admin、user.id在.env初始化允许列表且会话≤300秒时允许bootstrap。
- `REQ-SEC-001-N02`：MUST 使登录角色只提供bootstrap资格；业务权限由显式本地grant/ACL决定；本地disable优先并撤销会话。
- `REQ-SEC-001-N03`：MUST NOT 因is_task_admin/is_super_admin/全局role授权正文，或让登录覆盖本地禁用；禁止在线停用最后有效管理员。

### Inputs
有效ms_、规范角色、bootstrap允许列表、管理reason。

### Preconditions
PRE-SEC-001-01：本地身份已验证；高权限操作会话新鲜。

### Authoritative State
SOT：本地管理grant、local_enabled、identity_version。

### State Transition
未初始化→管理授权；ACTIVE→LOCAL_DISABLED；恢复→需重新登录。

### Allowed Side Effects
ALLOW：本地管理授权、策略版本、会话撤销、审计。

### Forbidden Side Effects
DENY：自动授予全会议读取/创建/下载，远程改用户状态。

### Ownership Scope
ROW：本地管理与撤销状态。
实施定位（目标，不表示已实现）：app/services/admin_service.py；app/api/admin/router.py；app/services/identity_service.py。

### Idempotency
已初始化bootstrap返回CONFLICT且0新grant；disable对已禁用成员保持状态。

### Failure Semantics
F-SEC-001-01：不在列表/角色不符→PERMISSION_DENIED；会话过旧→ADMIN_REAUTH_REQUIRED；最后管理员→LAST_ADMIN_DISABLE_FORBIDDEN。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-SEC-001-01：管理权限不自动等于内容权限；员工B默认没有A的资源权利。

### Invariants
INV-SEC-001：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
ADMIN_REAUTH_REQUIRED; LAST_ADMIN_DISABLE_FORBIDDEN; PERMISSION_DENIED。数值与HTTP语义以第9.7章为准。

### Acceptance
A-SEC-001-01, A-SEC-001-02。

### Evidence
required test：tests/identity/test_sec_001.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

## REQ-DATA-001 — 仅使用本地成员目录与可信腾讯映射

### Goal
替代上游search/resolve，不虚构从未登录过的员工。

### Normative Requirement
- `REQ-DATA-001-N01`：MUST 将成员选择和存在性校验改为查询当前组件、组织的LocalMember；只有ACTIVE且本地启用者可新建授权或腾讯绑定。
- `REQ-DATA-001-N02`：MUST NOT 为缺少员工执行远程搜索、按姓名匹配、自动创建可信成员或从.env注入统一员工身份。

### Inputs
成员查询字符串、member_id、腾讯userid/open_id映射。

### Preconditions
PRE-DATA-001-01：管理操作有对应本地权限；未知员工先主动账号登录。

### Authoritative State
SOT：LocalMember和原IdentityBinding。

### State Transition
已登录成员→可选择；未登记→LOCAL_MEMBER_NOT_ENROLLED。

### Allowed Side Effects
ALLOW：获批的腾讯身份绑定/本地grant；成员查询审计。

### Forbidden Side Effects
DENY：外部目录访问、跨组织搜索、把登录user.id当腾讯userid。

### Ownership Scope
ROW：本地成员/绑定。
实施定位（目标，不表示已实现）：app/services/portal_service.py；app/api/portal.py；app/services/admin_service.py；app/services/connection_service.py。

### Idempotency
查询不创建成员；同一绑定与旧实现冲突规则一致。

### Failure Semantics
F-DATA-001-01：未登记/LEGACY_UNVERIFIED→LOCAL_MEMBER_NOT_ENROLLED；重复冲突→IDENTITY_CONFLICT。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-DATA-001-01：列表明确标注“本地已登记成员”，不表示完整企业通讯录。

### Invariants
INV-DATA-001：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
IDENTITY_CONFLICT; LEGACY_UNVERIFIED; LOCAL_MEMBER_NOT_ENROLLED。数值与HTTP语义以第9.7章为准。

### Acceptance
A-DATA-001-01, A-DATA-001-02。

### Evidence
required test：tests/identity/test_data_001.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

## REQ-RUNTIME-001 — API、Worker及腾讯连接移除隐藏身份网络

### Goal
不仅登录入口，所有业务执行面均使用本地身份。

### Normative Requirement
- `REQ-RUNTIME-001-N01`：MUST 替换所有运行时 `.backend.context/resolve/search/ready` 调用；按第8.3章区分交互父会话和SERVICE本地批准。
- `REQ-RUNTIME-001-N02`：MUST 在员工作业执行及分页边界验证固定身份租期、组件/组织、禁用与权限；CREATE发送后继续记录真实结果。
- `REQ-RUNTIME-001-N03`：MUST NOT 在Worker自动重放账号密码、把SERVICE伪装为MEMBER或以本地缓存名义恢复旧Backend调用。

### Inputs
持久化Principal、连接操作者映射、作业状态。

### Preconditions
PRE-RUNTIME-001-01：API/Worker同auth_mode_epoch；成员映射可核对。

### Authoritative State
SOT：本地成员、父会话、Client/Grant/Binding及腾讯响应。

### State Transition
员工租期过期→未发送的作业FAILED；有效SERVICE批准→按原业务支持范围执行。

### Allowed Side Effects
ALLOW：作业状态、腾讯原允许调用、审计；无上游身份HTTP。

### Forbidden Side Effects
DENY：自动登录、扩大SERVICE创建、租期过期后首次发创建请求。

### Ownership Scope
FILE/ROW：所有运行路径及作业日志。
实施定位（目标，不表示已实现）：app/runtime.py；auth/admin/connection/maintenance/event/query/content/operation服务；腾讯client；Worker。

### Idempotency
原幂等创建键不变；失效作业不无限重试；新登录需显式重新提交未执行操作。

### Failure Semantics
F-RUNTIME-001-01：租期过期→IDENTITY_REAUTH_REQUIRED；本地停用→LOCAL_MEMBER_DISABLED；已发创建超时→原OUTCOME_UNKNOWN。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-RUNTIME-001-01：去掉特定Backend依赖但不删除身份、scope、ACL或人工确认检查。

### Invariants
INV-RUNTIME-001：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
IDENTITY_REAUTH_REQUIRED; LOCAL_MEMBER_DISABLED。数值与HTTP语义以第9.7章为准。

### Acceptance
A-RUNTIME-001-01, A-RUNTIME-001-02。

### Evidence
required test：tests/identity/test_runtime_001.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

## REQ-TXN-001 — 登录落库原子性与并发观察顺序

### Goal
避免登录返回成功但会话未提交，以及旧响应覆盖新状态。

### Normative Requirement
- `REQ-TXN-001-N01`：MUST 按第14章事务合同提交成员投影、观察、会话、策略版本与成功审计；令牌只在提交后返回。
- `REQ-TXN-001-N02`：MUST 使用attempt_seq拒绝较早登录响应覆盖同用户已经提交的较新观察；并发登录保持成员唯一。
- `REQ-TXN-001-N03`：MUST NOT 在本地失败时声称撤销上游登录副作用，或为恢复而再次发送密码请求。

### Inputs
attempt序号、规范化上游观察、数据库事务。

### Preconditions
PRE-TXN-001-01：上游响应已校验；成员唯一锁/约束存在。

### Authoritative State
SOT：数据库事务提交结果；上游last_login不属于可回滚范围。

### State Transition
T0→原子提交；写入失败→本地回T0；提交结果不确定→失败且等待核验。

### Allowed Side Effects
ALLOW：本地成员/会话/观察/成功审计；独立失败审计。

### Forbidden Side Effects
DENY：半提交身份、未提交Token返回、日志保存密码。

### Ownership Scope
ROW：TX-LOGIN受管集合。
实施定位（目标，不表示已实现）：app/services/login_service.py；app/core/database.py；app/models/identity.py。

### Idempotency
新登录是新会话；成员upsert幂等；同一attempt不产生两份观察。

### Failure Semantics
F-TXN-001-01：写中断→INTERNAL_ERROR；旧响应→CONFLICT；提交不确定→503，不自动重试。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-TXN-001-01：存在返回ms_必有可查询会话行；较新的停用观察不被旧成功覆写。

### Invariants
INV-TXN-001：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
CONFLICT; INTERNAL_ERROR。数值与HTTP语义以第9.7章为准。

### Acceptance
A-TXN-001-01, A-TXN-001-02。

### Evidence
required test：tests/identity/test_txn_001.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

## REQ-MIGRATE-001 — 旧成员映射与身份切换迁移

### Goal
保留历史资源与授权引用，不把旧成员的权利静默转交给新user.id。

### Normative Requirement
- `REQ-MIGRATE-001-N01`：MUST 按第16章完成dry-run、映射校验、备份、身份epoch切换、旧会话撤销和首次登录验证；旧member_id按映射承接。
- `REQ-MIGRATE-001-N02`：MUST NOT 按姓名/邮箱推断对应关系、删除未知旧数据、重新加密/重置腾讯凭据、在代码回退后自动启用旧身份网络。

### Inputs
受保护迁移manifest、当前数据库和新.env。

### Preconditions
PRE-MIGRATE-001-01：旧API/Worker停止接入；无正在执行的CREATE；备份已核验。

### Authoritative State
SOT：旧持久引用、批准manifest、迁移账本。

### State Transition
旧namespace→新已应用epoch；未核验旧成员保持LEGACY_UNVERIFIED。

### Allowed Side Effects
ALLOW：新增身份表、显式映射、member/agent旧Token撤销、迁移账本。

### Forbidden Side Effects
DENY：重写已授权资源owner、改腾讯凭据密文、改共享Backend代码/库。

### Ownership Scope
ROW/FILE：迁移受管范围及备份。
实施定位（目标，不表示已实现）：app/models/identity.py；Alembic增量；scripts/migrate_identity.py（新增）；docs/identity-migration.md（新增）。

### Idempotency
同manifest二次apply返回ALREADY_APPLIED；不同manifest拒绝；dry-run0业务写。

### Failure Semantics
F-MIGRATE-001-01：活跃引用未映射→IDENTITY_MIGRATION_REQUIRED；重复映射→IDENTITY_MAPPING_CONFLICT；提交不确定→IDENTITY_MIGRATION_UNCERTAIN。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-MIGRATE-001-01：授权引用ID保持；旧令牌不可用；新的真实登录后才激活承接身份。

### Invariants
INV-MIGRATE-001：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
IDENTITY_MAPPING_CONFLICT; IDENTITY_MIGRATION_REQUIRED; IDENTITY_MIGRATION_UNCERTAIN。数值与HTTP语义以第9.7章为准。

### Acceptance
A-MIGRATE-001-01, A-MIGRATE-001-02。

### Evidence
required test：tests/identity/test_migrate_001.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

## REQ-SEC-002 — 密码、Token和HTTP内网例外保护

### Goal
新的登录入口会经过账号密码，需要明确处理凭据泄露与明文内网风险。

### Normative Requirement
- `REQ-SEC-002-N01`：MUST 按第18章处理密码和票据：仅内存短生命周期、禁日志/Trace/APM请求体/异常原文，不保存上游Token。
- `REQ-SEC-002-N02`：MUST 仅为用户指定精确HTTP地址启用显式内网例外；外部调用网关仍使用HTTPS，关闭重定向及环境代理。
- `REQ-SEC-002-N03`：MUST NOT 声称该HTTP链路已加密，不接受任意URL，不把真实凭据用于文档/测试或回显给Hermes。

### Inputs
账号密码、私有HTTP许可、保护网络证据、合成泄露探针。

### Preconditions
PRE-SEC-002-01：实际路由可达；运维批准内网明文例外并保存证据；不自动探测登录健康。

### Authoritative State
SOT：受控配置/网络证据、服务端固定请求。

### State Transition
未批准HTTP→配置失败；批准→仅固定URL允许。

### Allowed Side Effects
ALLOW：密码用于一次出站请求；脱敏日志与本地随机Token哈希。

### Forbidden Side Effects
DENY：密码写.env/日志/DB；原始上游Token落盘；curl -k或全局不验TLS。

### Ownership Scope
REQUEST/FIELD：敏感输入与日志投影。
实施定位（目标，不表示已实现）：app/integrations/account_login/client.py；app/core/middleware.py；app/core/config.py；deploy/nginx.conf.example。

### Idempotency
日志检查可重复，不修改数据；密钥与会话不因日志扫描变化。

### Failure Semantics
F-SEC-002-01：无HTTP许可→IDENTITY_CONFIG_INVALID；异常不打印请求值；响应日志过滤失败→测试FAIL。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-SEC-002-01：所有证据文件均不含真实登录凭据；内网风险被明确记录而非隐去。

### Invariants
INV-SEC-002：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
IDENTITY_CONFIG_INVALID。数值与HTTP语义以第9.7章为准。

### Acceptance
A-SEC-002-01, A-SEC-002-02。

### Evidence
required test：tests/identity/test_sec_002.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

## REQ-SEC-003 — 登录限流、失败隔离和禁止密码重试

### Goal
避免登录代理变成绕过上游策略的口令重试器。

### Normative Requirement
- `REQ-SEC-003-N01`：MUST 实现第18章确定的客户端IP/账号桶限流、响应分类、一次attempt一次POST；429/超时/5xx不自动登录重试。
- `REQ-SEC-003-N02`：MUST NOT 因陌生账号字符串登录失败就停用同名本地成员；不得向调用方回显上游原始错误或账号存在性。

### Inputs
账号、可信网络源、上游状态或异常。

### Preconditions
PRE-SEC-003-01：分布式限流由数据库协调；代理来源仅由配置的可信代理确定。

### Authoritative State
SOT：RateLimit、attempt状态和严格上游响应。

### State Transition
额度内→一次请求；超限→本地429；上游失败→统一失败。

### Allowed Side Effects
ALLOW：限流桶和脱敏失败审计；合法成功状态变化按事务写。

### Forbidden Side Effects
DENY：错误账号攻击导致其他成员禁用，自动尝试备用登录接口。

### Ownership Scope
ROW：限流和审计。
实施定位（目标，不表示已实现）：app/services/login_service.py；app/services/rate_service.py；app/core/errors.py。

### Idempotency
重试由用户显式新attempt触发，仍计额度；超限请求不重置桶周期。

### Failure Semantics
F-SEC-003-01：本地超限→RATE_LIMITED；上游401/403→ACCOUNT_LOGIN_REJECTED；429/5xx/超时→ACCOUNT_LOGIN_UNAVAILABLE。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-SEC-003-01：上游无法访问时不能产生新身份；已有效会话在固定租期内按本地策略工作。

### Invariants
INV-SEC-003：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
ACCOUNT_LOGIN_REJECTED; ACCOUNT_LOGIN_UNAVAILABLE; RATE_LIMITED。数值与HTTP语义以第9.7章为准。

### Acceptance
A-SEC-003-01, A-SEC-003-02。

### Evidence
required test：tests/identity/test_sec_003.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

## REQ-CHECK-001 — 健康检查和诊断不再访问身份服务

### Goal
取消当前Backend健康探测及工具对backend=true的依赖。

### Normative Requirement
- `REQ-CHECK-001-N01`：MUST 使live/ready和后台心跳零身份HTTP；ready区分数据库/配置/最后已观察登录结果，不能把未探测标为上游可用。
- `REQ-CHECK-001-N02`：MUST NOT 用保存密码周期登录作为健康检查，或仅因身份服务离线判定数据库/回调接收进程死亡。

### Inputs
数据库连通性、已加载配置、可选历史脱敏诊断。

### Preconditions
PRE-CHECK-001-01：配置有效；无需先登录才能返回live。

### Authoritative State
SOT：本地配置与数据库；最后成功登录仅是历史Evidence。

### State Transition
未登录→identity configured且NOT_PROBED；登录后→只记录last_observed，不声称current_available。

### Allowed Side Effects
ALLOW：本地指标与数据库探测；保护诊断中的历史时间。

### Forbidden Side Effects
DENY：上游/health、/me或自动account-login。

### Ownership Scope
NONE/OBSERVABILITY：健康视图。
实施定位（目标，不表示已实现）：app/main.py；app/cli.py；app/services/diagnostic_service.py；integration-kit健康检查。

### Idempotency
重复健康检查不改变身份、会话、权限；检查次数不刷新观察。

### Failure Semantics
F-CHECK-001-01：数据库不可用→ready503；身份配置缺失→启动exit2；上游状态没有观察→NOT_PROBED。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-CHECK-001-01：联调脚本按新健康Schema判断，移除旧backend=true必需条件。

### Invariants
INV-CHECK-001：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
NOT_PROBED。数值与HTTP语义以第9.7章为准。

### Acceptance
A-CHECK-001-01, A-CHECK-001-02。

### Evidence
required test：tests/identity/test_check_001.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

## REQ-UI-001 — 本地登录入口与现有HTTP页面适配

### Goal
操作员可登录配置网关，但不要求另建一套业务平台。

### Normative Requirement
- `REQ-UI-001-N01`：MUST 为既有可选Portal增量或内部应用提供本地登录会话接入；登录表单只调用网关，管理/同意请求使用ms_。
- `REQ-UI-001-N02`：MUST NOT 在浏览器直接调用内网身份地址、专用成员接口、使用旧portal_token充当ms_，或把密码存localStorage。

### Inputs
用户主动填写账号密码、本地session过期/失效状态。

### Preconditions
PRE-UI-001-01：网关HTTPS入口与批准CORS；没有Portal也可用CLI走相同接口。

### Authoritative State
SOT：服务器本地会话；前端只是显示状态。

### State Transition
无会话→登录表单；成功→管理或原业务位置；401→清会话并重新登录。

### Allowed Side Effects
ALLOW：浏览器内存票据、用户显示状态、网关API请求。

### Forbidden Side Effects
DENY：新建员工密码库、修改整套上游登录体系、浏览器携带client_secret到公共脚本。

### Ownership Scope
FILE：Meeting前端增量与调用例子。
实施定位（目标，不表示已实现）：integration/portal/src/features/meeting/client.ts与视图；examples/rest_client.py；可选GatewayLogin.vue（新增）。

### Idempotency
重复进入视图不重复登录；禁止自动重发保存密码。

### Failure Semantics
F-UI-001-01：接口过期→显示IDENTITY_REAUTH_REQUIRED；未有管理权→403界面，不转到禁用接口。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-UI-001-01：CLI和内部系统无需Portal UI即可配置并联调；页面和接口认证语义一致。

### Invariants
INV-UI-001：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
第9.7章统一错误表。数值与HTTP语义以第9.7章为准。

### Acceptance
A-UI-001-01, A-UI-001-02。

### Evidence
required test：tests/identity/test_ui_001.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

## REQ-INTEGRATION-001 — integration-kit、部署手册与Hermes指令同步

### Goal
使实际服务器按新登录方法运行，避免工具继续要求身份桥。

### Normative Requirement
- `REQ-INTEGRATION-001-N01`：MUST 将工具身份准备改为用户不回显输入→网关account-login→本地ms_→exchange；按第24、26章产生脱敏证据。
- `REQ-INTEGRATION-001-N02`：MUST 更新Hermes提示词：不安装身份桥、不调用禁止接口、不在.env保存公共员工密码，不修改门禁制造PASS。
- `REQ-INTEGRATION-001-N03`：MUST NOT 自动改旧kit版本锁或声称此前工具已兼容；升级包与网关目标SHA成对验证。

### Inputs
本地目录、配对版本、操作员账号、真实客户端。

### Preconditions
PRE-INTEGRATION-001-01：已部署目标身份版本；工具只读预检先行；凭据放private不回显。

### Authoritative State
SOT：现场执行结果、配对manifest、请求轨迹。

### State Transition
旧kit→预检拒绝；新kit→按授权/只读/生态范围运行。

### Allowed Side Effects
ALLOW：private中的受控本地会话文件、evidence脱敏结果；网关账号登录动作。

### Forbidden Side Effects
DENY：记录上游Tokens、访问3条接口、调用上游refresh、修改证据状态。

### Ownership Scope
FILE：integration-kit及运维文档；不改主机其他服务。
实施定位（目标，不表示已实现）：integration-kit/tools与manual-checks；docs登录部署；Hermes执行提示词。

### Idempotency
预检重复0业务写；明确登录是新attempt；部署不覆盖已有.env与keyring。

### Failure Semantics
F-INTEGRATION-001-01：版本不匹配→工具exit2；缺网络或凭据→BLOCKED；未运行→NOT_RUN而非PASS。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-INTEGRATION-001-01：手册不再把BACKEND_SERVICE_TOKEN或/backend身份接口列为启动前提。

### Invariants
INV-INTEGRATION-001：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
BLOCKED。数值与HTTP语义以第9.7章为准。

### Acceptance
A-INTEGRATION-001-01, A-INTEGRATION-001-02。

### Evidence
required test：tests/identity/test_integration_001.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

## REQ-EVID-001 — 网络、源码与业务证据闭环

### Goal
用实际请求轨迹证明禁止接口未被调用，而不是仅grep几个字符串。

### Normative Requirement
- `REQ-EVID-001-N01`：MUST 按第24章绑定SHA、配置指纹、测试命令、时间、oracle与证据摘要；同时提供源码调用点检查及运行时网络负向捕获。
- `REQ-EVID-001-N02`：MUST NOT 将绿色测试、空请求日志、全部SKIPPED或只声明PASS当作零违规调用证明。

### Inputs
测试场景、出站记录器、生成代码/安装模板扫描、证据manifest。

### Preconditions
PRE-EVID-001-01：记录器先做正向控制证明能捕获一次真实或合成登录；真实账号不写记录器body。

### Authoritative State
SOT：执行轨迹和文件digest；状态标签只是派生结论。

### State Transition
有断言有证据→PASS；缺证据→BLOCKED；断言不符→FAIL。

### Allowed Side Effects
ALLOW：脱敏证据和报告文件。

### Forbidden Side Effects
DENY：把报告写回业务权限、把测试断言改成永远跳过。

### Ownership Scope
GENERATED_ONLY：evidence目录。
实施定位（目标，不表示已实现）：tests/identity与网络捕获夹具；scripts/check_identity_egress.py（新增）；reports（生成）。

### Idempotency
同一run重建报告只读取证据；不产生新登录/业务请求。

### Failure Semantics
F-EVID-001-01：未捕获正向控制/缺工件→EVIDENCE_INCOMPLETE；包含敏感探针→FAIL。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-EVID-001-01：每一条禁止行为有运行时负向用例，并排除文档中的禁止列表误报。

### Invariants
INV-EVID-001：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
EVIDENCE_INCOMPLETE; FAIL。数值与HTTP语义以第9.7章为准。

### Acceptance
A-EVID-001-01, A-EVID-001-02。

### Evidence
required test：tests/identity/test_evid_001.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

## REQ-REGRESSION-001 — 腾讯业务、权限与MCP不降级

### Goal
身份来源改造只缩减身份HTTP，不改变腾讯会议连接器的主用途。

### Normative Requirement
- `REQ-REGRESSION-001-N01`：MUST 对既有允许的AK/SK、OAuth本人查询/创建、STS、转写、纪要、下载、事件、MCP执行身份替换回归。
- `REQ-REGRESSION-001-N02`：MUST 保留现有客户端/资源/采集/人工确认/幂等和来源限制；所有相关身份读取走本地。
- `REQ-REGRESSION-001-N03`：MUST NOT 因本轮改造开放CORP_WINDOW、APPROVED_SERVICE、自动代他人创建或绕过腾讯授权；不修饰未实现能力为已完成。

### Inputs
已有功能Fixture、A/B本地身份、双通道合成/真实资源。

### Preconditions
PRE-REGRESSION-001-01：目标功能原本有实现；与身份无关的新能力仍按原边界。

### Authoritative State
SOT：原业务SOT＋本地主体；不从login角色导出内容权利。

### State Transition
替换身份验证→维持原允许/拒绝结果。

### Allowed Side Effects
ALLOW：被允许的腾讯调用、原业务持久状态、审计。

### Forbidden Side Effects
DENY：移除PermissionService、全量管理员默认授权、访问上游成员接口。

### Ownership Scope
FILE/RESOURCE：与身份相关调用点，不整体重写腾讯协议。
实施定位（目标，不表示已实现）：tests/integration；tests/acceptance；app/services各业务调用点；app/mcp。

### Idempotency
原创建幂等结果、scope交集、下载撤销语义不变。

### Failure Semantics
F-REGRESSION-001-01：未知员工→LOCAL_MEMBER_NOT_ENROLLED；会话过期→IDENTITY_REAUTH_REQUIRED；原腾讯拒绝保留原错误类别。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-REGRESSION-001-01：原基线用例更新身份夹具后仍验证同一业务oracle，不靠删测试降级。

### Invariants
INV-REGRESSION-001：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
IDENTITY_REAUTH_REQUIRED; LOCAL_MEMBER_NOT_ENROLLED。数值与HTTP语义以第9.7章为准。

### Acceptance
A-REGRESSION-001-01, A-REGRESSION-001-02。

### Evidence
required test：tests/identity/test_regression_001.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

## REQ-CMD-001 — 可部署配置、升级及回滚边界

### Goal
指定服务器升级后不能混跑新旧身份协议或覆盖已有腾讯配置。

### Normative Requirement
- `REQ-CMD-001-N01`：MUST 按第16、17章冻结目标版本、生成新配置差异、检查namespace/epoch、先迁移后启动，API/Worker配置一致。
- `REQ-CMD-001-N02`：MUST 使安装器在本版不再向nodeskclaw-backend添加文件或路由；本地check不调用身份接口。
- `REQ-CMD-001-N03`：MUST NOT 自动执行docker down -v、覆盖keyring、切到旧身份实现、把无执行证据的部署标为VERIFIED。

### Inputs
配对部署包、.env、数据库备份和命名空间记录。

### Preconditions
PRE-CMD-001-01：维护窗口；目标服务器内网账号登录可达性由显式登录验证，不抓取私密配置。

### Authoritative State
SOT：commit SHA、DB迁移版本、applied_config_digest。

### State Transition
PRECHECK→BACKUP→MIGRATED→STARTED→CHECKED；失败不自动downgrade到旧身份。

### Allowed Side Effects
ALLOW：本项目受管配置/镜像/迁移和脱敏报告。

### Forbidden Side Effects
DENY：其他项目文件、上游服务修改、删除卷/凭据。

### Ownership Scope
FILE/ROW：网关部署边界。
实施定位（目标，不表示已实现）：app/cli.py；scripts/integrate.py；deploy；Alembic；README与版本manifest。

### Idempotency
相同配置重复预检无写；重复迁移按manifest识别；重启不重新生成身份密钥。

### Failure Semantics
F-CMD-001-01：版本/epoch不符→启动exit2；迁移未完成→IDENTITY_MIGRATION_REQUIRED；镜像未能验证→BLOCKED。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-CMD-001-01：不依赖额外成员桥；保留PostgreSQL与私有存储独立部署。

### Invariants
INV-CMD-001：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
BLOCKED; IDENTITY_MIGRATION_REQUIRED。数值与HTTP语义以第9.7章为准。

### Acceptance
A-CMD-001-01, A-CMD-001-02。

### Evidence
required test：tests/identity/test_cmd_001.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

## REQ-GOLDEN-001 — 真实账号登录与内部系统联调

### Goal
静态响应和mock不能替代用户指定地址上的实际账号登录。

### Normative Requirement
- `REQ-GOLDEN-001-N01`：MUST 使用第26章的真实消费者、A/B账号、指定唯一登录接口、现场网关及配对kit形成账号登录和会议读取证据。
- `REQ-GOLDEN-001-N02`：MUST 将未提供或未执行的真实场景标BLOCKED/NOT_RUN；身份改造发布的全部Required Acceptance不是PASS时门禁非零。
- `REQ-GOLDEN-001-N03`：MUST NOT 使用用户粘贴的Token直接认证、把原报告搬作新证据、或为验证而自动创建真实会议。

### Inputs
现场运行版本、批准的测试账号、非敏感已知会议、实际授权。

### Preconditions
PRE-GOLDEN-001-01：用户自行在SSH/可信界面不回显输入密码；HTTP内网风险记录；禁止接口网络记录可验证。

### Authoritative State
SOT：直接account-login结果与现场执行工件。

### State Transition
未执行→NOT_RUN；阻断→BLOCKED；实际符合→PASS。

### Allowed Side Effects
ALLOW：真实用户登录产生的上游副作用、批准的腾讯只读请求、网关本地数据与脱敏证据。

### Forbidden Side Effects
DENY：未经批准真实写会议、采集无权限内容、将未执行写场景标通过。

### Ownership Scope
EVIDENCE/RESOURCE：明确授权的联调范围。
实施定位（目标，不表示已实现）：integration-kit/evidence；现场执行报告；docs/identity-login-only-acceptance.md（新增）。

### Idempotency
每次run独立证据；不复用旧账号Token；业务重复查询仍受原幂等/授权约束。

### Failure Semantics
F-GOLDEN-001-01：现场请求体或响应不符合→ACCOUNT_LOGIN_CONTRACT_ERROR并阻断；无法观测→BLOCKED。
本地事务失败的回滚作用域限于第14章受管行；脱敏失败审计/限流计数和已完成的上游登录不属于可撤销部分。可重试仅指新的显式操作，不自动重放密码。

### Postconditions
POST-GOLDEN-001-01：能证明账号登录后内部系统使用网关本地身份调腾讯，且零禁止身份接口。

### Invariants
INV-GOLDEN-001：第10章本需求全部规范在重复调用、失败和进程重启时不被放宽；第20章正向和负向Acceptance共同约束这些规范。

### Error Codes
BLOCKED。数值与HTTP语义以第9.7章为准。

### Acceptance
A-GOLDEN-001-01, A-GOLDEN-001-02。

### Evidence
required test：tests/identity/test_golden_001.py（新增）；required artifact：每个A的`evidence/<run_id>/<acceptance_id>.json`；required digest：第13章定义的受管状态/工件摘要；required runtime output：命令退出码、HTTP及具体oracle，不记录敏感请求body。

# 11. Side-Effect Contract

以下矩阵由 REQ-API-001、REQ-TXN-001、REQ-SEC-002、REQ-CMD-001共同约束。“只读”只针对注明的业务范围；日志、限流和缓存也是副作用，不隐去。

| Operation | DB Write | File Write | Network | Cache | User Data | Business Source |
|---|---|---|---|---|---|---|
| 配置check / 迁移dry-run | 0业务写 | 脱敏报告 | 不访问身份/腾讯；可连接本地DB | 仅进程内 | 不改 | 不改 |
| account-login | 本地成员/观察/会话/审计/限流 | 受控日志，无body | 唯一上游登录POST一次 | 不缓存密码/上游Token | 更新最小化资料 | 上游可能写登录时间/会话/审计，不能回滚 |
| session检查 / auth exchange | 交换时本地Token/审计 | 脱敏日志 | 0身份HTTP | 可用请求级缓存 | 不改变源资料 | 不改 |
| 本地members查询 | 仅审计 | 脱敏日志 | 0身份HTTP | 不回填未登记成员 | 不改源身份 | 不改 |
| 本地disable/enable/logout | 本地状态/策略/令牌撤销 | 审计 | 0身份HTTP | 清当前授权缓存 | 不写上游员工 | 不改腾讯凭据 |
| health/ready | 0业务写 | 指标 | 只连接本地DB | 不更新身份新鲜度 | 不改 | 不改 |
| 腾讯OAuth刷新/STS | 原凭据/票据状态 | 原脱敏日志 | 腾讯网络，0内部身份HTTP | 原票据缓存 | 无密码 | 仅原允许腾讯操作 |
| 员工会议读/写/Worker | 原业务合同 | 正文/证据按原策略 | 腾讯网络；本地身份检查 | 不延长父租期 | 按已有授权 | 按原幂等/确认规则 |
| identity migration apply | 明确迁移行 | 受保护备份/账本 | 本地DB；0上游接口 | 失效旧身份缓存 | 显式承接ID，不转移授权归属 | 腾讯凭据/资源不改 |
| 报告汇总 | 0业务写 | evidence报告 | 0 | 0 | 不含正文/密钥 | 不改 |

账号密码不通过队列、作业payload或事件传播。成功响应包含ms_是唯一允许的明文会话交付；DB、日志和一般诊断不得保存同值。

# 12. Ownership Contract

## 12.1 所有权

| 类型 | Owner | 可更新内容 | 不可覆盖内容 |
|---|---|---|---|
| `.env` | USER_OWNED，运维 | 明确批准的新身份配置字段 | KEYRING、数据库密码、腾讯凭据、无关变量 |
| 网关源码 | FILE/SECTION，项目 | 第16.4节列明的身份相关代码 | 无关会议业务和第三方服务 |
| 成员资料 | FIELD，IdentityService | 经白名单验证的显示资料和观察状态 | local_enabled、既有member_id、未经批准授权 |
| 本地权限 | ROW，授权服务 | 有权限管理员的显式授予/撤销 | 不能由登录响应替换 |
| 迁移映射 | ENTRY，管理员批准manifest | 一一对应且有证据的条目 | 未知所有权旧条目 |
| 腾讯凭据/业务资源 | USER_OWNED / 既有服务 | 本轮仅引用 | 移除旧身份不等于重置腾讯Secret/Token |
| 测试证据 | GENERATED_ONLY | 本run目录 | 其他run或人工原始证据 |

## 12.2 Drift

`current_digest == last_applied_digest` 才允许自动更新受管配置字段；否则返回DRIFT并阻断apply。没有上次摘要时，执行只读diff并要求显式批准，不能把未知文件认作生成文件。相同配置重放只返回already_applied。

禁止通过符号链接访问项目根以外配置或备份；迁移输入和输出路径均做resolve包含性检查。失败备份保留权限0600；任何自动清理不触碰未知所有权文件。上述规则由REQ-MIGRATE-001、REQ-CMD-001验收。

# 13. Hash / Identity Contract

## 13.1 外部与本地身份

外部user.id、配置org_id均解析为标准小写UUID。组件ID按第9章ASCII规则校验，不trim后默默接受错误值。issuer_id固定为 `account-login-v1`。

没有承接映射的新成员ID：

```python
uuid.uuid5(
    uuid.NAMESPACE_URL,
    "meeting-gateway/account-login/v1/"
    + component_id + "/" + org_id + "/account-login-v1/" + external_user_id
)
```

UUIDv5仅用于确定性身份命名，不是密码学认证；不能凭算出的member_id调用接口。持久库中已有一一对应映射时优先使用已批准的legacy_member_id，禁止再创建UUIDv5并转移旧权限。

## 13.2 票据及观察摘要

- ms_：`"ms_" + urlsafe_base64(CSPRNG(32 bytes)).rstrip("=")`，不含姓名/组织/角色信息。数据库保存 `SHA256(token UTF-8)`；令牌原值不存DB。若测试注入重复哈希，最多重新生成3次，仍重复则整个TX-LOGIN失败，不能重发上游登录。
- 业务mt_/mr_继续原随机与哈希合同；本轮不更改创建幂等键或文件内容hash范围。
- 规范JSON字节：UTF-8、键名字典序、无多余空白、数组保留业务顺序、禁止NaN；时间为UTC RFC3339六位小数，UUID统一标准形式。
- `projection_digest`：SHA256(规范JSON({issuer_id,user_id,org_id,normalized_role,is_active,must_change_password,needs_org_setup,expires_in,attempt_seq,received_at}))。不含密码、上游Token、姓名或邮箱。
- `applied_config_digest`：SHA256(规范JSON({schema_version,identity_mode,component_id,org_id,issuer_id,login_url,session_ttl,admin_fresh_seconds,http_exception,bootstrap_user_ids排序去重}))；不含任何Secret值。
- 日志中账号限流桶：HMAC-SHA256(现有keyring派生`login-rate`密钥, casefold(trim(account)) UTF-8)；只用于限流，不用于匹配成员，密码不参与hash。

## 13.3 文件与数据证据

单文件证据摘要 `SHA256(file_bytes)`；源码树摘要为相对POSIX路径按字节序排序，对每项连接 `path UTF-8 + NUL + SHA256(file_bytes).digest()` 再做SHA256；排除.git、.venv、private、真实.env、密钥、备份和生成报告。排除列表随manifest固定保存。

迁移业务摘要对表名/主键排序后的选定列规范JSON做SHA256；租期、ID、授权、密文等受管数据均参与各自摘要。失败审计和限流计数单列为可变化副作用，不混入“0mutation”判定。腾讯Credential密文以密文字节做摘要，永不解密导出用于比对。真实个人资料只留本地受控表，Evidence不含原始内容。REQ-EVID-001负责检验证据摘要与排除规则。

# 14. Transaction Contract

## 14.1 TX-LOGIN边界

顺序：验证本地请求及限流 → 分配全局单调attempt_seq → 直接上游登录 → 校验并投影 → 开启本地事务并锁成员唯一键 → 比较观察顺序 → 更新LocalMember → 追加LoginObservation → 写IdentitySession与成功审计 → COMMIT → 返回ms_。

事务包括：这次成员创建/资料更新、观察记录、会话、策略版本、因可信状态变化触发的旧会话撤销及成功审计。事务不包括：上游登录副作用、请求限流、单独失败审计、HTTP响应发送。密码和上游令牌不进入事务字段。

`T0`是上述受管行第一次写入前的快照。提交前任一失败：受管行回到T0；失败日志/attempt计数可保留。提交结果不明：不返回票据，不自动补发login；运维按attempt_id核对本地事务。

## 14.2 顺序与并发

attempt_seq在上游请求前分配。对同一user只接受 `attempt_seq > LocalMember.last_applied_attempt_seq` 的观察；落后响应返回CONFLICT，不覆盖投影、不开新会话。此规则是本地确定性防回退规则，不声称能推断上游并发登录执行顺序。

明确返回is_active=false或must_change_password=true的合法身份响应，可以对该组件/组织内已存在的对应成员提交状态拒绝、版本递增及撤销，然后返回403；这是**已提交的安全撤销事务**，不能被外层异常回滚。错误密码、畸形响应或错误组织不能凭account字符串修改任何用户状态。

角色或active/force-change标记发生变化时增加identity_version并撤销旧会话；显示名、邮箱变更不撤销旧会话。已存在本地会议grant不因角色变化自动改写；下次新会话仍受本地显式权限约束，bootstrap资格按最新规范角色检查。

## 14.3 TX-DISABLE

锁成员 → 检查最后管理员规则 → 设置local_enabled/state/identity_version → 撤销全部成员及关联AGENT会话/令牌族/未消费授权码 → bump策略版本 → 写审计 → COMMIT。其他进程在下次授权边界读到新版本；本版不使用跨请求的身份正向缓存。

## 14.4 TX-MIGRATE和恢复

迁移前停API/Worker，拒绝在CREATE=EXECUTING时继续。备份文件和摘要通过后，事务内写新表映射、身份epoch、旧Token撤销、迁移账本。提交前失败回T0；提交后发现异常不重放apply。需要恢复时由运维使用受保护备份恢复本地DB，并保持服务停止，不能自动运行旧代码重新调用禁止接口。

恢复失败：`IDENTITY_MIGRATION_UNCERTAIN`、服务保持阻断、保留备份与账本、不自动删除`.env`和任何密钥。对上游账号登录、腾讯创建或已下载字节不承诺回滚。REQ-TXN-001、REQ-MIGRATE-001、REQ-RUNTIME-001约束这些边界。

# 15. Conflict Contract

| Conflict | Detection | Default Behavior | Error | Mutation |
|---|---|---|---|---|
| 组件或组织与DB不一致 | 配置digest/namespace逐字段比较 | BLOCK | IDENTITY_NAMESPACE_MISMATCH | 0业务写 |
| user.id有两个候选旧member | manifest与DB唯一约束 | BLOCK | IDENTITY_MAPPING_CONFLICT | 0 |
| 同member指向两个外部用户 | manifest一一映射校验 | BLOCK | IDENTITY_MAPPING_CONFLICT | 0 |
| 同名不同用户 | user.id不同 | 保留两个成员，不合并 | 无，非冲突 | 各自有明确登录才可创建 |
| 本地disabled但远端active | local_enabled优先 | DENY | LOCAL_MEMBER_DISABLED | 不自动enable |
| 客户端自报更高role/org | Strict Schema拒绝 | DENY | INVALID_REQUEST | 0特权写 |
| 旧成功响应晚于新观察 | attempt_seq比较 | BLOCK | CONFLICT | 0身份写 |
| 已有bootstrap | PolicyVersion/管理授权检查 | BLOCK | CONFLICT | 0新grant |
| .env/受管文件人工漂移 | current与last_applied摘要不同 | PRESERVE + BLOCK APPLY | IDENTITY_CONFIG_INVALID（附DRIFT阶段） | 0覆盖 |
| session/mapping并发 | 唯一索引/行锁 | 单条成员、一致观察 | CONFLICT或幂等返回 | 不使用last writer wins |

# 16. Compatibility / Migration

## 16.1 旧状态与行为变化

旧版本基线为第1章固定SHA。旧ms_会话不存在；管理入口依赖Backend Bearer，exchange依赖Backend subject_token，身份成员指向OrgMembership。新模式统一切换到本地会话，不双栈接收旧Backend JWT。

保留：腾讯应用、OAuth/STS/AKSK密文、Meeting/Recording/Asset、既有成员授权和资源来源字段、REST业务路径、MCP工具、客户端与创建策略。改变：认证凭据语义、成员来源、健康检查、初始化、部署变量、工具登录方式。

`/api/v1/auth/exchange`保持路径和字段形状，但subject_token语义发生破坏性变化，需和内部客户端/kit一起发布。旧Token收到IDENTITY_REAUTH_REQUIRED或IDENTITY_MODE_CHANGED，不进行网络补验。

## 16.2 迁移manifest/1

```json
{
  "schema_version": "1",
  "component_id": "meeting-gateway",
  "org_id": "<配置UUID>",
  "from_commit": "79e22d08b623a4f7816db05af631a463fe14348b",
  "target_commit": "<实际待发布完整SHA>",
  "approved_by": "<实际审批记录标识>",
  "entries": [
    {"legacy_member_id":"<旧成员ID>","external_user_id":"<已核对user.id>","evidence_ref":"<受保护映射证据编号>"}
  ]
}
```

Schema additionalProperties=false。输入不含密码/Token。映射来源可以是本地持久化的明确user_id/member_id对应关系加人工核对记录；不能只凭姓名、邮箱或上游JWT的未验证payload。已有历史对应关系也仅用于承接ID，新模式首次有效登录后才能变成ACTIVE。

需映射的活跃引用包括：启用的AccessGrant/IdentityBinding/Connection/Client.owner/AgentGrant/Subscription.member/SyncPolicy对应操作者，以及尚未结束作业的MEMBER主体。任一缺映射阻断apply。仅在旧历史审计中出现、无活跃引用的ID可原样保留为历史未解析标识，不创建有效成员或迁移其权利。

## 16.3 迁移执行合同

`detect → dry-run → preserve snapshot → approved apply → verify → start new runtime`。

- dry-run只报告行数、缺映射、冲突、版本和摘要；不调用上游，不生成新管理员。
- apply先确认无执行中CREATE和所有进程处于维护窗口；自动生成Alembic结构变更后应用已审查迁移。
- 同manifest二次apply为ALREADY_APPLIED。不同manifest对已应用epoch返回CONFLICT，不能静默重新映射。
- 旧member/agent AccessToken、未消费下游授权码和上游OAuth登录事务失效；不撤销腾讯OAuth持久连接本身。
- 未执行的旧员工CREATE/内容作业转失败并记录IDENTITY_MODE_CHANGED；已发出且不确定的CREATE保持OUTCOME_UNKNOWN与关联材料，不伪造已失败。
- 旧SERVICE客户端和授权保留，但映射成员未首次登录验证前不得作为新的已验证操作者；不会为了绕过这一要求生成假的ACTIVE成员。
- 不访问、删除或修改上游Backend已安装的身份桥代码；仅停止本项目对它的使用。

## 16.4 文件/符号改造定位

下表是实施定位，非已改动清单；审查来自连接器逐文件读取，不宣称已经完成全仓库符号扫描。

| 当前文件/符号 | 目标改造 |
|---|---|
| `app/runtime.py::Runtime.__init__/close` | 删除默认BackendClient装配；装配AccountLoginClient和本地IdentityService；业务层不直接调用login transport |
| `app/integrations/nodeskclaw_backend/client.py` | 从运行入口删除；本版不可保留可调用旧端点的fallback对象 |
| 新`app/integrations/account_login/client.py` | 仅暴露`login(account,password)`，固定URL/方法与严格响应投影 |
| 新`app/services/identity_service.py` | `require_session`负责认证；`lookup_local_member`只查目录；`require_local_operator`核对本地操作者；不混同三者 |
| `app/core/config.py` / `app/cli.py` | 新配置、旧变量阻断、namespace一致性、非回显配置生成 |
| `app/core/types.py` / 新`app/models/identity.py` | 本地成员与会话、Principal父会话/epoch字段 |
| `app/services/auth_service.py` | portal_principal、_principal、revalidate、exchange、refresh、approve_authorization改本地校验 |
| `app/api/deps.py` / `authorization/router.py` / 新`api/identity.py` | ms_认证、登录/登出/会话查询、exchange语义切换 |
| `admin_service.py` | human、bootstrap、引用校验、成员绑定/客户端owner全部本地化 |
| `connection_service.py` | OAuth开始/回调/确认与AKSK操作者校验用本地身份；持久腾讯凭据不作为内部会话 |
| `integrations/tencent_meeting/client.py` | 请求前的`.backend.resolve`改本地操作者检查；腾讯签名与路径不变 |
| `event_service.py` / `maintenance_service.py` | 接收方/定时同步的身份校验本地化，移除维护期间对成员服务访问 |
| query/content/operation/sync/download服务及Worker | 绑定父身份租期；对失效任务终止而非用密码自动登录 |
| `app/main.py` / `diagnostic_service.py` | 删除上游health；区分本地就绪和历史登录观察 |
| `permission_service.py` | 继续现有ACL交集；目录查询不代替授权；新增local_enabled/epoch约束 |
| integration Portal/client/locale | 不再自动读取Backend portal_token；改网关登录会话，保留可选页面 |
| `scripts/integrate.py` | 新模式不写Backend项目；旧Backend桥列为obsolete但不擅自移除上游文件 |
| `.env.example`、README、Compose、源码/kitmanifest | 配置与版本成对更新，去掉旧服务Token前置条件 |
| integration-kit、Hermes提示词 | 登录方法、会话文件、health字段、negative请求和报告口径全部同步 |

# 17. External Dependency Contract

## 17.1 登录服务

| 属性 | 合同 |
|---|---|
| Endpoint | 用户指定固定POST account-login，见第0章 |
| 现场版本 | 未从输入取得SHA；真实验收记录部署方提供的版本号或“未提供版本信息”并保存本次合同探测摘要，不伪造版本 |
| 所需API | 只有账号登录，禁止其他身份HTTP |
| 请求Schema | `{account,password}`，历史参考[S21]；现场只通过该接口确认，不访问OpenAPI或成员服务探测 |
| offline | 新登录失败；已有未过期本地会话按本地权利工作；到期必须显式重新登录 |
| fallback | 无；不接备用成员接口、不保存密码自动补偿 |
| 失败处理 | 第9.7章映射；每个attempt最多一个HTTP请求 |
| 可信度边界 | 登录响应只反映上游此时返回的资料，不能证明未来状态或服务未返回的成员数据 |

**历史参考的限制：**[S21]中的UserInfo序列化器会把must_change_password输出为false。这只能证明那个历史快照的行为，不证明用户指定服务器当前行为。本稿要求对实际收到的true拒绝，但不能通过这一接口恢复被上游隐藏的真实状态。现场报告要记录该限制；不以字段false宣称账号后台绝无强制改密状态，也不因此调用被禁接口纠正数据。

## 17.2 其他依赖

| 依赖 | 版本/身份规则 | 本轮边界 |
|---|---|---|
| 网关源代码 | 基线固定SHA；发布使用实际target SHA，拒绝仅写master | 只读研究不等于修改/测试完成 |
| PostgreSQL/Alembic | 沿用仓库版本约束；target lock与镜像digest进入Evidence | 会话/映射/策略持久状态，不新增Redis必需依赖 |
| 腾讯会议 | 保留已有AKSK/OAuth/STS的原接口和授权 | 不受“内部账号登录仅一接口”的同源限制 |
| 内部系统 | 登记客户端及scope，配对target SHA/kitmanifest | 不把上游Token上传作为新的可信身份 |
| Hermes | 仅为部署运维执行者 | 不获得会议Agent委托，不读取/回显私有凭据 |

## 17.3 来源索引

本稿依据用户本轮要求、用户给出的登录响应结构及附件模板。代码事实使用以下固定链接；第S21是历史参考，S22—S24是补充安全/库文档，不替代用户目标。

- [S01] 网关基线：https://github.com/smc-copilot/meeting-gateway/commit/79e22d08b623a4f7816db05af631a463fe14348b

- [S02] 现有 Backend 身份适配器：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/integrations/nodeskclaw_backend/client.py

- [S03] 运行时依赖装配：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/runtime.py

- [S04] 身份与主体结构：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/core/types.py

- [S05] 身份会话、令牌交换、MCP 授权：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/services/auth_service.py

- [S06] 生产环境配置校验：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/core/config.py

- [S07] 管理员初始化与成员绑定：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/services/admin_service.py

- [S08] 腾讯连接、OAuth、STS：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/services/connection_service.py

- [S09] 腾讯请求前的员工核验：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/integrations/tencent_meeting/client.py

- [S10] 权限判断与资源来源：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/services/permission_service.py

- [S11] Worker 作业调度：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/worker.py

- [S12] 事件、订阅与接收方授权：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/services/event_service.py

- [S13] 健康检查：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/main.py

- [S14] 网关令牌交换与授权路由：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/authorization/router.py

- [S15] 内部业务接口：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/api/business.py

- [S16] Portal HTTP 接口：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/api/portal.py

- [S17] 部署环境生成器：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/cli.py

- [S18] Compose 部署：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/deploy/compose.yaml

- [S19] 现有主体模式下的创建边界：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/services/operation_service.py

- [S20] 源查询与本人连接限制：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/services/query_service.py

- [S21] 历史上游 AccountLoginRequest 参考；不是现场版本证明：https://github.com/loudon84/nodeskclaw/blob/83edfb0d97f07920deb8bb9ce44a91e3e32cc3af/nodeskclaw-backend/app/schemas/auth.py

- [S22] HTTPX 环境变量行为：https://www.python-httpx.org/environment_variables/

- [S23] HTTPX 请求与重定向参数：https://www.python-httpx.org/api/

- [S24] OWASP 会话期限与服务端失效参考：https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html

- [S25] 既有冻结数值错误码：https://github.com/smc-copilot/meeting-gateway/blob/79e22d08b623a4f7816db05af631a463fe14348b/app/core/errors.py

# 18. Security Contract

以下具体控制纳入REQ-SEC-001/002/003与REQ-API-001；安全背景参考[S22—S24]，900秒租期等数值是本项目设计，不声称来自外部标准的强制值。

| Threat | Control | Acceptance |
|---|---|---|
| 客户端伪造user或仅JWT解码认证 | 只由固定上游直接成功交换生成本地身份，拒绝外部subject_token | A-API-002-02、A-AUTH-002-02 |
| 明文内网密码/Token被窃听 | 默认不允许HTTP；此次精确地址需显式例外和运维风险记录，网关外部HTTPS；不宣称内网天然可信 | A-SEC-002-01/02、A-GOLDEN-001-02 |
| 代理/重定向泄露密码 | trust_env=false、follow_redirects=false、精确origin/path、无客户端URL | A-API-001-02 |
| 密码/Token进入日志/APM/Hermes | 禁请求体/原始响应/异常字符串；synthetic canary扫描；CLI不回显、private目录0700/文件0600 | A-SEC-002-01 |
| brute force/账号枚举 | 账号桶5次/300秒；客户端IP桶20次/60秒；集群登录并发最多5；统一登录拒绝文案；上游不重试 | A-SEC-003-01/02 |
| 组件/组织越界 | 固定.env+持久namespace+响应组织比较；角色无权覆盖组织 | A-CONFIG-001-02、A-IDENTITY-001-02 |
| 本地管理员引导劫持 | env允许列表 AND 当次组织角色admin AND 300秒新鲜度；登录不自动授权 | A-SEC-001-01 |
| 撤权后旧缓存继续使用 | 每次请求本地查当前身份/会话/策略，无跨请求正向身份缓存；分页/下载边界重验 | A-AUTH-001-01、A-REGRESSION-001-02 |
| SESSION无限刷新 | 固定父租期，refresh不越界；不使用上游refresh_token | A-AUTH-001-02 |
| 旧数据权限错绑 | 一一映射manifest，冲突阻断，首次登录前UNVERIFIED | A-MIGRATE-001-01/02 |
| path traversal/symlink/任意执行 | 脚本只写受管目录，禁止shell拼接账号/URL，resolve路径包含性校验 | A-MIGRATE-001-02、A-CMD-001-02 |
| 下游回调绕行到身份host | 通知/media目标允许列表不得包含身份origin；同源只准login专用transport访问 | A-API-001-02 |

限流实现：数据库固定窗口，键为HMAC账号或可信客户端IP，不持久化原始密码；超限不延长窗口。可信IP来自明确配置的反向代理链，未配置时只用socket peer，不信任任意X-Forwarded-For。并发额度在集群共享，不是每个API副本各5个。登录请求连接超时3秒，总超时10秒，最大响应256KiB，3xx不跟随。上游401/403/非零code对外使用统一ACCOUNT_LOGIN_REJECTED，不输出“该员工存在但密码错”。

保留期限：会话终态行7天后可按软删除/保留策略清理，LoginObservation与脱敏身份审计保留180天；LocalMember作为授权引用存在期间不物理删除。禁止密码或上游Token为排查而暂存。内存字符串不能承诺物理清零，保证的是不持久化、缩短对象引用生命周期且关闭相关body追踪。

# 19. Observability

阶段：`CONFIG_CHECK → LOGIN_VALIDATE → LOGIN_UPSTREAM → LOGIN_PROJECT → LOGIN_COMMIT → LOCAL_AUTH → AUTHORIZE → TENCENT_EXECUTE → EVIDENCE`。迁移另有`MIGRATION_ANALYZE/APPLY/VERIFY/RECOVERY_REQUIRED`。

每个事件字段：operation_id/attempt_id、stage、status、UTC timestamp、component_id、org_id（已知且允许时）、target_commit、reason/error_code、HTTP method及固定path标识、elapsed_ms、可公开resource_id。禁止账号密码、原始login body、上游Token、Authorization、下载票据、会议正文。

新指标：`identity_login_attempts_total{result}`、`identity_egress_blocked_total{category}`、`identity_session_rejections_total{reason}`、`identity_migration_status`。禁止把账号、Token或用户邮箱做指标label。受保护诊断可给最后成功登录观察时间及“非实时状态”的标签；公用health仅给数据库/配置就绪，不公布用户最近登录资料。

新ready示例（无任何身份出站）：

```json
{"status":"ok","database":true,"identity":{"mode":"account_login","configured":true,"validation":"NOT_PROBED"}}
```

该validation仅表示本次健康请求不主动探测上游，不应在登录后永久改成“上游当前可用”。受保护诊断单独返回历史`last_successful_login_at`。

# 20. Acceptance Design Standard

下列为待实现/待执行的验收定义，不是已通过记录。测试文件、工具新参数和Evidence路径均为本版目标交付物。每个Acceptance关联对应REQ的全部规范；标注Negative的用例验证禁止行为。命令环境使用隔离测试库，真实Golden仅在用户指定服务器执行。

## A-API-001-01 — 一个登录、其他阶段零身份出站

### Requirement Refs
REQ-API-001；Positive Acceptance（正向）。

### Given
模拟固定上游返回合法登录；其余上游路由均设为测试即失败。

### When
登录后执行管理、交换、业务读取、MCP、OAuth确认、Worker维护和health。

### Then
只有一次身份POST，三个禁止接口及其他身份URL计数均为0。

### Oracle
```text
identity_http_count==1; disallowed_identity_http_count==0; methods_paths==[(POST,account-login)]
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-API-001-01
command: "uv run pytest tests/identity/test_api_001.py::test_case_01 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-API-001-01.json"
evidence_id: EVID-A-API-001-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-API-001-02 — 重定向、代理和绕行拒绝

### Requirement Refs
REQ-API-001；Negative Acceptance（负向）。

### Given
分别设置302到resolve、HTTP_PROXY陷阱、带查询/编码路径/其他地址。

### When
执行登录或加载异常配置。

### Then
不跟随、不代理、不调用备用端点。

### Oracle
```text
redirect_target_calls==0; proxy_calls==0; privileged_mutations==0
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-API-001-02
command: "uv run pytest tests/identity/test_api_001.py::test_case_02 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-API-001-02.json"
evidence_id: EVID-A-API-001-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-CONFIG-001-01 — 无旧凭据启动且进程一致

### Requirement Refs
REQ-CONFIG-001；Positive Acceptance（正向）。

### Given
同一新.env，无两个旧字段，空身份表。

### When
启动API、Worker两次。

### Then
记录同一namespace，两次启动不增加部署行。

### Oracle
```text
deployment_rows==1; backend_client_instances==0; api_namespace==worker_namespace
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-CONFIG-001-01
command: "uv run pytest tests/identity/test_config_001.py::test_case_01 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-CONFIG-001-01.json"
evidence_id: EVID-A-CONFIG-001-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-CONFIG-001-02 — 组件漂移和旧配置拒绝

### Requirement Refs
REQ-CONFIG-001；Negative Acceptance（负向）。

### Given
已有组件A/组织A数据；分别改组件、组织、填入旧服务Token。

### When
启动进程。

### Then
exit2且不修改成员、授权、腾讯密文。

### Oracle
```text
exit_code==2; business_digest_before==business_digest_after
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-CONFIG-001-02
command: "uv run pytest tests/identity/test_config_001.py::test_case_02 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-CONFIG-001-02.json"
evidence_id: EVID-A-CONFIG-001-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-API-002-01 — 用户样本结构的合法登录

### Requirement Refs
REQ-API-002；Positive Acceptance（正向）。

### Given
固定上游合法响应；JWT为合成占位字符串；role=user且portal_org_role=admin。

### When
通过本地登录接口提交账号密码。

### Then
本地返回自己的ms_与用户投影，无上游Token字段。

### Oracle
```text
http==200; session_prefix==ms_; response_contains_upstream_tokens==false; outbound_body_keys==[account,password]
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-API-002-01
command: "uv run pytest tests/identity/test_api_002.py::test_case_01 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-API-002-01.json"
evidence_id: EVID-A-API-002-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-API-002-02 — 伪造响应和错误类型拒绝

### Requirement Refs
REQ-API-002；Negative Acceptance（负向）。

### Given
请求额外提交user；或上游code=false/is_active="true"/缺user.id/重复JSON键/超256KiB。

### When
分别发起登录。

### Then
所有失败均不新增有效会话。

### Oracle
```text
new_active_sessions==0; extra_input_upstream_calls==0; reasons in [INVALID_REQUEST,ACCOUNT_LOGIN_CONTRACT_ERROR]
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-API-002-02
command: "uv run pytest tests/identity/test_api_002.py::test_case_02 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-API-002-02.json"
evidence_id: EVID-A-API-002-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-IDENTITY-001-01 — 重复登录身份稳定且角色正确

### Requirement Refs
REQ-IDENTITY-001；Positive Acceptance（正向）。

### Given
同user两次登录，第二次修改姓名/邮箱；给定用户role=user、portal_org_role=admin。

### When
归一化并落库。

### Then
一个成员、ID不变、member_role=admin但无自动业务授权。

### Oracle
```text
member_count==1; id1==id2; grants_created_by_login==0; normalized_role==admin
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-IDENTITY-001-01
command: "uv run pytest tests/identity/test_identity_001.py::test_case_01 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-IDENTITY-001-01.json"
evidence_id: EVID-A-IDENTITY-001-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-IDENTITY-001-02 — 组织、共享ID与角色扩权拒绝

### Requirement Refs
REQ-IDENTITY-001；Negative Acceptance（负向）。

### Given
两用户同名；一用户组织不符；另一用户portal角色缺失且is_task_admin=true。

### When
依次登录。

### Then
同名用户ID不同；错组织拒绝；任务管理员不获会议权。

### Oracle
```text
id_userA!=id_userB; mismatch_reason==ACCOUNT_ORG_MISMATCH; unknown_role==member; business_grants==0
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-IDENTITY-001-02
command: "uv run pytest tests/identity/test_identity_001.py::test_case_02 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-IDENTITY-001-02.json"
evidence_id: EVID-A-IDENTITY-001-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-AUTH-001-01 — 900秒身份租期与登出

### Requirement Refs
REQ-AUTH-001；Positive Acceptance（正向）。

### Given
上游expires_in=86400；网关TTL900；已发ms_和mt_。

### When
推进到900秒并重放，或先主动登出。

### Then
后续认证拒绝且没有外部HTTP。

### Oracle
```text
effective_deadline==t0+900s; t>=deadline_http==401; raw_session_tokens_in_db==0; identity_network_after_login==0
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-AUTH-001-01
command: "uv run pytest tests/identity/test_auth_001.py::test_case_01 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-AUTH-001-01.json"
evidence_id: EVID-A-AUTH-001-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-AUTH-001-02 — 延长期限和伪JWT拒绝

### Requirement Refs
REQ-AUTH-001；Negative Acceptance（负向）。

### Given
客户端提交看似合法HS256 JWT；或在第899秒刷新mt_。

### When
认证或刷新后推进到父期限。

### Then
JWT不能直接作为会话；派生期限不超过父期限。

### Oracle
```text
external_jwt_http==401; child_expires_at<=parent_expires_at; expired_refresh_issue_count==0
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-AUTH-001-02
command: "uv run pytest tests/identity/test_auth_001.py::test_case_02 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-AUTH-001-02.json"
evidence_id: EVID-A-AUTH-001-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-AUTH-002-01 — 本地exchange和两种受众

### Requirement Refs
REQ-AUTH-002；Positive Acceptance（正向）。

### Given
A已登录，客户端有read，另有合法agent委托。

### When
exchange和PKCE分别获取REST/MCP令牌并调用。

### Then
成功且不访问任何外部身份端点。

### Oracle
```text
exchange_http==200; local_scope_intersection==expected; identity_http_delta==0
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-AUTH-002-01
command: "uv run pytest tests/identity/test_auth_002.py::test_case_01 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-AUTH-002-01.json"
evidence_id: EVID-A-AUTH-002-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-AUTH-002-02 — 令牌与主体混用拒绝

### Requirement Refs
REQ-AUTH-002；Negative Acceptance（负向）。

### Given
使用旧BackendJWT、ms_调用业务、REST mt_调用MCP、AGENT调用确认。

### When
发起请求。

### Then
全部拒绝且腾讯写调用为0。

### Oracle
```text
all_denied==true; tencent_create_calls==0; identity_http_delta==0
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-AUTH-002-02
command: "uv run pytest tests/identity/test_auth_002.py::test_case_02 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-AUTH-002-02.json"
evidence_id: EVID-A-AUTH-002-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-SEC-001-01 — 管理员资格和显式授权

### Requirement Refs
REQ-SEC-001；Positive Acceptance（正向）。

### Given
给定输入用户在初始化列表，portal_org_role=admin、role=user。

### When
登录后bootstrap；再调用未授权内容接口。

### Then
bootstrap成功但正文被拒；显式grant后按范围放行。

### Oracle
```text
management_grant_count==1; content_before_grant==403_or_404; after_grant==expected
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-SEC-001-01
command: "uv run pytest tests/identity/test_sec_001.py::test_case_01 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-SEC-001-01.json"
evidence_id: EVID-A-SEC-001-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-SEC-001-02 — 禁用不可被登录覆盖

### Requirement Refs
REQ-SEC-001；Negative Acceptance（负向）。

### Given
A有多个会话，B为另一个有效管理员。

### When
B禁用A，A再次正确登录；尝试停用最后管理员。

### Then
A所有会话无效且重新登录拒；最后管理员不被禁。

### Oracle
```text
active_sessions_A==0; login_A_reason==LOCAL_MEMBER_DISABLED; last_admin_reason==LAST_ADMIN_DISABLE_FORBIDDEN
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-SEC-001-02
command: "uv run pytest tests/identity/test_sec_001.py::test_case_02 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-SEC-001-02.json"
evidence_id: EVID-A-SEC-001-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-DATA-001-01 — 本地成员可用于绑定

### Requirement Refs
REQ-DATA-001；Positive Acceptance（正向）。

### Given
A已真实登录，B从未登录。

### When
管理员查询并为A建立真实映射。

### Then
只查询本地目录；A可绑定；不返回B。

### Oracle
```text
search_network_calls==0; member_rows_delta==0; binding_member_id==A.local_id
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-DATA-001-01
command: "uv run pytest tests/identity/test_data_001.py::test_case_01 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-DATA-001-01.json"
evidence_id: EVID-A-DATA-001-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-DATA-001-02 — 未知成员、重名及跨组织拒绝

### Requirement Refs
REQ-DATA-001；Negative Acceptance（负向）。

### Given
不存在member_id、另组织ID、同名外部用户。

### When
尝试绑定和授权。

### Then
不创建新的可信成员、不访问上游search。

### Oracle
```text
new_members==0; grants_to_unknown==0; forbidden_http_count==0
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-DATA-001-02
command: "uv run pytest tests/identity/test_data_001.py::test_case_02 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-DATA-001-02.json"
evidence_id: EVID-A-DATA-001-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-RUNTIME-001-01 — Worker后台维护无身份HTTP

### Requirement Refs
REQ-RUNTIME-001；Positive Acceptance（正向）。

### Given
可用本地SERVICE采集批准、腾讯绑定和合成腾讯响应；所有上游身份接口不可达。

### When
运行STS、OAuth刷新、事件处理和作业领取。

### Then
按原能力执行且只访问腾讯，不访问登录服务。

### Oracle
```text
identity_http_delta==0; tencent_calls==expected; service_not_promoted_to_member==true
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-RUNTIME-001-01
command: "uv run pytest tests/identity/test_runtime_001.py::test_case_01 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-RUNTIME-001-01.json"
evidence_id: EVID-A-RUNTIME-001-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-RUNTIME-001-02 — 作业到期与发送边界

### Requirement Refs
REQ-RUNTIME-001；Negative Acceptance（负向）。

### Given
员工CREATE排队后父会话过期；另一个CREATE已发送后过期。

### When
Worker执行或处理响应。

### Then
前者0腾讯写；后者不丢已发结果，保留真实journal。

### Oracle
```text
before_send_create_calls==0; sent_operation_state in [SUCCEEDED,FAILED,OUTCOME_UNKNOWN]; automatic_login_calls==0
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-RUNTIME-001-02
command: "uv run pytest tests/identity/test_runtime_001.py::test_case_02 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-RUNTIME-001-02.json"
evidence_id: EVID-A-RUNTIME-001-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-TXN-001-01 — 并发身份唯一

### Requirement Refs
REQ-TXN-001；Positive Acceptance（正向）。

### Given
两个成功登录attempt到达同外部用户，顺序可控。

### When
并发提交。

### Then
一名成员、独立会话；序号高的观察为当前投影。

### Oracle
```text
local_member_count==1; unique_session_hashes==true; current_attempt_seq==max(committed_seq)
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-TXN-001-01
command: "uv run pytest tests/identity/test_txn_001.py::test_case_01 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-TXN-001-01.json"
evidence_id: EVID-A-TXN-001-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-TXN-001-02 — 中断及乱序不产生半身份

### Requirement Refs
REQ-TXN-001；Negative Acceptance（负向）。

### Given
在成员写入后、会话写入前注入数据库错误；另测试旧成功响应晚于新停用观察。

### When
执行登录。

### Then
本地投影/会话/成功审计回T0；旧响应不复活账号。

### Oracle
```text
transaction_managed_digest_after==before; issued_tokens==0; stale_response_can_enable==false
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-TXN-001-02
command: "uv run pytest tests/identity/test_txn_001.py::test_case_02 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-TXN-001-02.json"
evidence_id: EVID-A-TXN-001-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-MIGRATE-001-01 — 迁移保留身份引用和腾讯凭据

### Requirement Refs
REQ-MIGRATE-001；Positive Acceptance（正向）。

### Given
有旧members引用和一一映射manifest，备份有效。

### When
dry-run后apply两次，并真实或模拟可信登录。

### Then
旧ID及ACL引用保留，腾讯密文未变，旧Token失效。

### Oracle
```text
dry_run_mutations==0; legacy_member_id==local_member_id; tencent_cipher_digest_same==true; second_apply==ALREADY_APPLIED
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-MIGRATE-001-01
command: "uv run pytest tests/identity/test_migrate_001.py::test_case_01 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-MIGRATE-001-01.json"
evidence_id: EVID-A-MIGRATE-001-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-MIGRATE-001-02 — 缺映射、冲突和回滚失败保护

### Requirement Refs
REQ-MIGRATE-001；Negative Acceptance（负向）。

### Given
活跃绑定缺映射、同user对应两旧member、或在事务内注入失败。

### When
执行迁移。

### Then
前两类0mutation；失败回T0；恢复失败保留备份并阻断服务。

### Oracle
```text
mapping_fail_exit==2; managed_digest_after==T0; recovery_backup_exists==true
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-MIGRATE-001-02
command: "uv run pytest tests/identity/test_migrate_001.py::test_case_02 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-MIGRATE-001-02.json"
evidence_id: EVID-A-MIGRATE-001-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-SEC-002-01 — 精确HTTP许可与脱敏

### Requirement Refs
REQ-SEC-002；Positive Acceptance（正向）。

### Given
配置精确用户URL并批准HTTP例外，使用唯一合成密码和Token。

### When
成功、失败、校验异常、网络异常各执行一次。

### Then
只允许固定URL，日志/DB/证据无敏感探针。

### Oracle
```text
canary_password_occurrences==0; upstream_token_occurrences==0; allowed_identity_destination_count==1
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-SEC-002-01
command: "uv run pytest tests/identity/test_sec_002.py::test_case_01 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-SEC-002-01.json"
evidence_id: EVID-A-SEC-002-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-SEC-002-02 — 无许可和任意地址不放行

### Requirement Refs
REQ-SEC-002；Negative Acceptance（负向）。

### Given
关闭HTTP许可或将配置换到另一主机/端口/path。

### When
启动或登录。

### Then
在发请求之前拒绝，不自动改HTTPS地址或关闭检查。

### Oracle
```text
outbound_requests==0; exit_code==2_or_http503
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-SEC-002-02
command: "uv run pytest tests/identity/test_sec_002.py::test_case_02 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-SEC-002-02.json"
evidence_id: EVID-A-SEC-002-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-SEC-003-01 — 限流与可用会话独立

### Requirement Refs
REQ-SEC-003；Positive Acceptance（正向）。

### Given
同账号5分钟内已5次尝试；已有正常用户会话。

### When
第6次登录；同时使用已有会话查询本地权限。

### Then
新登录429且不上游，已有会话不被外部故障自动删除。

### Oracle
```text
sixth_upstream_calls==0; http==429; unrelated_session_revoked==false
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-SEC-003-01
command: "uv run pytest tests/identity/test_sec_003.py::test_case_01 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-SEC-003-01.json"
evidence_id: EVID-A-SEC-003-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-SEC-003-02 — 网络和错误口令不重试不禁他人

### Requirement Refs
REQ-SEC-003；Negative Acceptance（负向）。

### Given
上游分别返回500/429/401/超时；账号与他人用户名相似。

### When
每种发起一次登录。

### Then
最多一次POST，无本地成员禁用副作用，无新会话。

### Oracle
```text
each_attempt_post_count<=1; unrelated_member_digest_same==true; new_sessions==0
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-SEC-003-02
command: "uv run pytest tests/identity/test_sec_003.py::test_case_02 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-SEC-003-02.json"
evidence_id: EVID-A-SEC-003-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-CHECK-001-01 — 空库健康不触发登录

### Requirement Refs
REQ-CHECK-001；Positive Acceptance（正向）。

### Given
应用首次启动，尚无账号登录，数据库可用。

### When
多次调用live/ready和Worker心跳。

### Then
HTTP200、identity配置有效但未探测，0身份HTTP。

### Oracle
```text
live_http==200; ready.identity.validation==NOT_PROBED; login_calls==0
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-CHECK-001-01
command: "uv run pytest tests/identity/test_check_001.py::test_case_01 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-CHECK-001-01.json"
evidence_id: EVID-A-CHECK-001-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-CHECK-001-02 — 上游断网不制造健康通过证据

### Requirement Refs
REQ-CHECK-001；Negative Acceptance（负向）。

### Given
曾登录后上游不可达。

### When
只调用ready。

### Then
不声称上游current_available=true，不生成新的身份观察。

### Oracle
```text
new_observations==0; upstream_live_assertion_present==false
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-CHECK-001-02
command: "uv run pytest tests/identity/test_check_001.py::test_case_02 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-CHECK-001-02.json"
evidence_id: EVID-A-CHECK-001-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-UI-001-01 — 页面与CLI共用本地会话

### Requirement Refs
REQ-UI-001；Positive Acceptance（正向）。

### Given
合成登录服务、有效本地grant。

### When
分别通过页面和CLI登录并访问配置。

### Then
两者都用网关入口；浏览器无内网请求。

### Oracle
```text
browser_identity_host_requests==0; management_header_prefix==Bearer_ms_; cli_result==expected
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-UI-001-01
command: "uv run pytest tests/identity/test_ui_001.py::test_case_01 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-UI-001-01.json"
evidence_id: EVID-A-UI-001-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-UI-001-02 — 旧浏览器令牌和密码留存检查

### Requirement Refs
REQ-UI-001；Negative Acceptance（负向）。

### Given
浏览器已有portal_token并发生登录失败/刷新。

### When
访问Meeting管理页。

### Then
不把旧Token兑换为可信身份；存储/日志无密码。

### Oracle
```text
old_backend_token_accepted==false; password_in_storage==false; forbidden_requests==0
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-UI-001-02
command: "uv run pytest tests/identity/test_ui_001.py::test_case_02 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-UI-001-02.json"
evidence_id: EVID-A-UI-001-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-INTEGRATION-001-01 — 成对工具完成登录与交换

### Requirement Refs
REQ-INTEGRATION-001；Positive Acceptance（正向）。

### Given
目标源码和kit manifest匹配，测试账号受控。

### When
运行工具的登录、交换、权限查询、报告。

### Then
只有login出站，报告记录真实通过断言与证据。

### Oracle
```text
required_steps_actual==true; report_contains_sha_and_oracle==true; banned_identity_calls==0
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-INTEGRATION-001-01
command: "uv run pytest tests/identity/test_integration_001.py::test_case_01 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-INTEGRATION-001-01.json"
evidence_id: EVID-A-INTEGRATION-001-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-INTEGRATION-001-02 — 旧版本和占位结果不通过

### Requirement Refs
REQ-INTEGRATION-001；Negative Acceptance（负向）。

### Given
旧kit仍要求Backend或HTTP202未完成。

### When
运行预检/报告。

### Then
拒绝或BLOCKED，非零退出；不编辑版本锁。

### Oracle
```text
exit_code!=0; report_pass==false; lockfile_unchanged==true
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-INTEGRATION-001-02
command: "uv run pytest tests/identity/test_integration_001.py::test_case_02 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-INTEGRATION-001-02.json"
evidence_id: EVID-A-INTEGRATION-001-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-EVID-001-01 — 可验证的零违规调用

### Requirement Refs
REQ-EVID-001；Positive Acceptance（正向）。

### Given
已执行完整测试矩阵，包含一个合法登录和故意尝试禁用路径。

### When
导出证据并验digest。

### Then
合法被捕获；违规被本地拒绝且网络零到达；全部AC有oracle。

### Oracle
```text
positive_control_count==1; forbidden_socket_requests==0; missing_evidence_count==0
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-EVID-001-01
command: "uv run pytest tests/identity/test_evid_001.py::test_case_01 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-EVID-001-01.json"
evidence_id: EVID-A-EVID-001-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-EVID-001-02 — 空日志/跳过/伪造PASS拒绝

### Requirement Refs
REQ-EVID-001；Negative Acceptance（负向）。

### Given
没有正向登录或把状态写PASS但无工件。

### When
运行门禁。

### Then
报告非PASS且exit2。

### Oracle
```text
release_status in [FAIL,BLOCKED]; exit_code==2
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-EVID-001-02
command: "uv run pytest tests/identity/test_evid_001.py::test_case_02 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-EVID-001-02.json"
evidence_id: EVID-A-EVID-001-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-REGRESSION-001-01 — 双通道正向回归

### Requirement Refs
REQ-REGRESSION-001；Positive Acceptance（正向）。

### Given
A有真实本地身份与授权，腾讯用合成fixture，双通道原功能可用。

### When
运行查询/创建/STS/内容/下载/事件/MCP套件。

### Then
业务结果与目标合同一致，身份HTTP只有显式登录。

### Oracle
```text
business_oracles_pass==true; original_denials_preserved==true; forbidden_http_count==0
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-REGRESSION-001-01
command: "uv run pytest tests/identity/test_regression_001.py::test_case_01 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-REGRESSION-001-01.json"
evidence_id: EVID-A-REGRESSION-001-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-REGRESSION-001-02 — 员工B和受众隔离

### Requirement Refs
REQ-REGRESSION-001；Negative Acceptance（负向）。

### Given
B单独登录但无A资源权限，另外构造SERVICE和越界MCP请求。

### When
读取A资源、下载、代创建或错误受众调用。

### Then
全部拒绝；没有更高权连接fallback。

### Oracle
```text
A_resource_disclosed_to_B==false; fallback_credentials_used==false; banned_identity_calls==0
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-REGRESSION-001-02
command: "uv run pytest tests/identity/test_regression_001.py::test_case_02 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-REGRESSION-001-02.json"
evidence_id: EVID-A-REGRESSION-001-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-CMD-001-01 — 新模式部署与重启

### Requirement Refs
REQ-CMD-001；Positive Acceptance（正向）。

### Given
隔离PostgreSQL、.env无旧Backend字段、配对镜像。

### When
迁移并启动API/Worker，重复重启。

### Then
所有进程namespace一致，数据/腾讯密文稳定，check0身份HTTP。

### Oracle
```text
api_worker_epoch_equal==true; stored_cipher_digest_same==true; check_identity_calls==0
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-CMD-001-01
command: "uv run pytest tests/identity/test_cmd_001.py::test_case_01 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-CMD-001-01.json"
evidence_id: EVID-A-CMD-001-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-CMD-001-02 — 混版本与跨服务写入拒绝

### Requirement Refs
REQ-CMD-001；Negative Acceptance（负向）。

### Given
Worker旧epoch或安装器目标目录包含Backend。

### When
执行启动和新模式安装dry-run。

### Then
拒绝混跑；不对Backend做任何写入。

### Oracle
```text
start_exit==2; backend_tree_digest_before==after; volumes_deleted==false
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-CMD-001-02
command: "uv run pytest tests/identity/test_cmd_001.py::test_case_02 -q"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-CMD-001-02.json"
evidence_id: EVID-A-CMD-001-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-GOLDEN-001-01 — 现场账号与腾讯只读闭环

### Requirement Refs
REQ-GOLDEN-001；Positive Acceptance（正向）。

### Given
指定服务器、新目标SHA、真实A/B账号和双方各自有效登录、明确会议样本。

### When
运行本地login→exchange→双通道实际已授权内容读→B负向→报告。

### Then
只账号登录出站；主体/组织正确；A内容匹配；B拒绝。

### Oracle
```text
real_login_count>=2; forbidden_identity_count==0; content_reference_match==true; B_denied==true; evidence_digest_valid==true
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-GOLDEN-001-01
command: "python integration-kit/tools/report.py --scope identity-login-only --require-live"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-GOLDEN-001-01.json"
evidence_id: EVID-A-GOLDEN-001-01
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

## A-GOLDEN-001-02 — 真实条件不足不能发布

### Requirement Refs
REQ-GOLDEN-001；Negative Acceptance（负向）。

### Given
缺B账号、无上游连通/拒绝HTTP风险、或只运行mock。

### When
生成发布报告。

### Then
按原因BLOCKED，exit2；不宣称现场通过。

### Oracle
```text
release_gate!=PASS; process_exit==2; upstream_tokens_in_evidence==0
```
复合oracle的每一项均记录expected/actual。任何一项不满足则本A失败，不能只保留HTTP状态。

### Evidence
```yaml
test_id: TEST-A-GOLDEN-001-02
command: "python integration-kit/tools/report.py --scope identity-login-only --require-live"
expected_exit_code: 0
pre_digest: "按第13章对该A受管状态计算"
post_digest: "按该A具体oracle比较，不一律要求相同"
artifact: "evidence/<run_id>/A-GOLDEN-001-02.json"
evidence_id: EVID-A-GOLDEN-001-02
```
这里的expected_exit_code=0指验收测试本身确认预期结果，包括成功捕获被测命令exit2的负向场景；不把被测业务命令失败冒充成功。

# 21. Acceptance Input Matrix

同一A的测试可参数化；不能只执行happy path。下面的高风险输入属于对应A的必需数据集，测试报告逐case保留结果。

| Requirement | normal / existing | empty / missing / invalid | duplicate / drift / boundary | retry / failure / rollback | Acceptance |
|---|---|---|---|---|---|
| API-001 | 一次固定login | 其他host/path/method | 编码路径、双斜线、redirect | 代理陷阱、自动重试检测 | A-API-001-01/02 |
| CONFIG-001 | API/Worker一致 | 缺component/org/keyring | 改组件/组织、旧变量残留 | config应用中断、重启 | A-CONFIG-001-01/02 |
| API-002 | 用户提供结构的脱敏fixture | 缺id/布尔、code=false、token_type错 | 超16KiB/256KiB、重复键 | timeout、非JSON、status矛盾 | A-API-002-01/02 |
| IDENTITY-001 | 同user资料变更 | org=null、角色null | 两人同名、旧映射冲突 | 资料投影失败 | A-IDENTITY-001-01/02 |
| AUTH-001 | 固定租期内 | 无ms_、旧JWT | t=deadline-1与deadline；随机碰撞 | logout、refresh、响应丢失 | A-AUTH-001-01/02 |
| AUTH-002 | client+session交集 | 缺clientsecret/错误scope | 管理/REST/MCP受众互换 | refresh重用、委托撤销 | A-AUTH-002-01/02 |
| SEC-001 | 双因子bootstrap资格 | role或允许列表不符 | 已bootstrap、最后管理员 | 本地禁用后新登录 | A-SEC-001-01/02 |
| DATA-001 | 已登录A | 未登记B | 同名、另组织、部分旧映射 | 查无成员不出站补全 | A-DATA-001-01/02 |
| RUNTIME-001 | 合法SERVICE维护 | 员工无有效session | 队列等待跨租期 | 创建发送前/后过期 | A-RUNTIME-001-01/02 |
| TXN-001 | 全部提交 | 校验失败0特权写 | 并发user/乱序观察 | 每个FI登录点 | A-TXN-001-01/02 |
| MIGRATE-001 | 全量一一映射 | 活跃引用缺映射 | 重复映射/manifest漂移 | apply与恢复失败 | A-MIGRATE-001-01/02 |
| SEC-002 | 精确HTTP例外 | 无批准/其他HTTP | 路径跳转、symlink | 异常日志/敏感探针 | A-SEC-002-01/02 |
| SEC-003 | 额度以内 | 空账号/错误密码 | 第5/6次、第20/21次 | 上游429/500/timeout | A-SEC-003-01/02 |
| CHECK-001 | DB可用 | 首次未登录 | 历史登录早已过期 | 上游断网、DB断网 | A-CHECK-001-01/02 |
| UI-001 | ms_登录 | 旧portal_token | 页面刷新/过期 | 错误返回不存密码 | A-UI-001-01/02 |
| INTEGRATION-001 | 配对kit/SHA | 缺账号/配置 | 旧工具和manifest漂移 | 202未完成/报告缺证据 | A-INTEGRATION-001-01/02 |
| EVID-001 | 完整记录 | 空日志/缺工件 | 修改证据digest | SKIPPED与伪PASS | A-EVID-001-01/02 |
| REGRESSION-001 | 双通道允许 | 未授权B | 错client/audience/source | 腾讯拒绝、会话撤销 | A-REGRESSION-001-01/02 |
| CMD-001 | 受控新部署 | 无迁移/旧参数 | 混epoch/用户文件漂移 | 启动失败/禁止自动回退 | A-CMD-001-01/02 |
| GOLDEN-001 | 真实A/B与样本 | 缺B或会议 | 现场版本与宣称不符 | 服务不可达/无证据 | A-GOLDEN-001-01/02 |

# 22. Negative Acceptance

每个REQ都有一个`-02`负向A。统一禁止事项由以下可观测拒绝覆盖：

| 禁止事项 | 判定 |
|---|---|
| 三条接口或其他身份HTTP被调用 | 网络捕获到任意一条即FAIL；不能以请求失败/返回404抵消 |
| 用静态user JSON、旧JWT或公共.env成员冒充认证 | ms_/mt_签发数为0 |
| 以任务管理员/全局管理员覆盖组织或内容权 | 错组织403；无grant正文403/404 |
| 通过local members查询建立新可信身份 | 查询前后成员表摘要不变 |
| 父租期到期后刷新或后台重新登录 | refresh拒绝；自动login请求数0 |
| 登录响应覆盖本地禁用 | local_enabled仍false；新有效会话数0 |
| 缺映射即按姓名继承ACL | apply拒绝且授权引用摘要不变 |
| 报告输出凭据或正文 | 合成canary扫描非零命中即FAIL |
| 通过重写版本锁/跳过测试生成PASS | manifest未授权变更或必需A缺证据即门禁非零 |

不存在`DEV_SKIP_AUTH`、`FAKE_BACKEND`、固定ACTIVE成员或绕过受众的发布开关。

# 23. Failure Injection

| FI ID | 注入点 | 确定postcondition | Acceptance |
|---|---|---|---|
| FI-01 | 本地请求校验之前 | 无身份HTTP，无有效session，最多脱敏审计 | A-API-002-02 |
| FI-02 | 上游login连接/读超时 | 一次attempt最多一次POST，未签发session，不重试 | A-SEC-003-02 |
| FI-03 | 上游302指向被禁接口 | 不跟随，目标调用0 | A-API-001-02 |
| FI-04 | LocalMember写后、Session写前 | TX-LOGIN回T0，成功审计不存在 | A-TXN-001-02 |
| FI-05 | Session写后、COMMIT前 | 所有身份受管行回T0，不返回票据 | A-TXN-001-02 |
| FI-06 | COMMIT成功、响应丢失 | 数据已提交，可有不可达用户的短期session；不重新POST密码，不宣称上游回滚 | A-TXN-001-02 |
| FI-07 | 新停用观察先提交、旧成功后到达 | 旧响应CONFLICT，不启用用户 | A-TXN-001-02 |
| FI-08 | mt_刷新落库前失败 | 新令牌不交付；父固定租期不变；按原刷新事务回滚 | A-AUTH-001-02 |
| FI-09 | 本地disable提交后另一Worker开始任务 | 该Worker下一次授权点拒绝，0新增腾讯写 | A-RUNTIME-001-02 |
| FI-10 | CREATE已发出后身份过期/网络断开 | 原journal保留真实成功或OUTCOME_UNKNOWN，不重发 | A-RUNTIME-001-02 |
| FI-11 | 迁移首行写后/最终提交前 | 映射和epoch回T0；备份保留 | A-MIGRATE-001-02 |
| FI-12 | 迁移提交结果不明或恢复失败 | 服务保持停止，IDENTITY_MIGRATION_UNCERTAIN，备份和账本保留 | A-MIGRATE-001-02 |
| FI-13 | config文件stage后、替换前 | 原.env不变；不覆盖用户密钥 | A-CMD-001-02 |
| FI-14 | 测试执行后、receipt写前异常 | 本A缺证据，不因测试日志green计PASS | A-EVID-001-02 |
| FI-15 | 代理环境变量指向记录器 | 代理收到密码请求数0 | A-API-001-02 |
| FI-16 | 上游离线期间定时health/维护 | health不触发login；SERVICE按本地批准和腾讯结果判断 | A-CHECK-001-02、A-RUNTIME-001-01 |

# 24. Evidence Contract

## 24.1 单项回执

```json
{
  "acceptance_id": "A-API-001-01",
  "status": "NOT_RUN",
  "requirement_ids": ["REQ-API-001"],
  "normative_ids": ["REQ-API-001-N01", "REQ-API-001-N02"],
  "test_ids": ["TEST-A-API-001-01"],
  "repo": "smc-copilot/meeting-gateway",
  "baseline_sha": "79e22d08b623a4f7816db05af631a463fe14348b",
  "tested_sha": null,
  "dirty": null,
  "config_digest": null,
  "component_id": null,
  "org_id": null,
  "timestamp": null,
  "command": null,
  "exit_code": null,
  "oracle": {"type":"identity_request_set","expected":{"forbidden_count":0},"actual":null},
  "positive_control_observed": false,
  "evidence_files": [],
  "tool_versions": {}
}
```

例子是未执行Schema，不是通过回执。完成的回执中tested_sha、时间、command、exit_code、actual和工件摘要均非空。现场身份请求只记录方法/固定目标/状态/关联ID，不记录密码、响应Token或Authorization；不能通过保存原始网络包泄露明文HTTP密码来“提供证据”。

## 24.2 证据目录

```text
meeting-integration-kit/
  private/                     # 0700；会话及客户端凭据0600；不进入报告/归档
  evidence/<run_id>/
    manifest.json
    configuration.json         # 无真实secret值
    identity-requests.jsonl     # 已去body和敏感header，含正向捕获控制
    migration.json
    A-*.json
    test-results.xml
    forbidden-endpoints.json
    release-gate.json
    report.md
```

对话中曾出现的真实Token不能拷贝为测试fixture。历史报告仅作为背景，不挪到本run充当新代码证据。

## 24.3 验证层次

1. Schema/纯函数：字段、角色、ID和期限。
2. 进程级合成：真实API/Worker调用路径＋带网络计数器的上游模拟；禁止端点收到请求即失败。
3. PostgreSQL：事务、索引、并发、迁移和多进程撤销。
4. 真实消费者：指定服务器账号登录和已授权腾讯只读闭环。

空日志不证明没调用，需正向控制证明采集器能看见允许的login。源码检查允许文档/测试负向列表中出现被禁止路径，但不可存在可执行调用，须报告位置分类而非仅字符串计数。

# 25. Release Gate

| Gate | 必需结果 | 不通过处理 |
|---|---|---|
| DOC | 本PRD结构/引用一致，用户完成评审批准 | REVIEW状态不能自动生成实施计划 |
| IDENTITY-CODE | 第20章全部合成/负向/事务/迁移/回归A通过 | 任一FAIL/BLOCKED/SKIPPED则exit2 |
| IDENTITY-LIVE | 真实登录及A/B/禁止接口0调用/批准会议只读有证据 | 未执行不计PASS，身份改造发布阻断 |
| BUSINESS-ECO | 如发布范围包含真实创建/媒体/事件，则沿原业务验收另验 | 未纳入本次现场读范围的真实写不标PASS；不能宣称全生态验证 |

完整身份改造版本发布要求`IDENTITY-CODE`和`IDENTITY-LIVE`同时PASS。受控部署用于收集LIVE证据可以标DEPLOYED_FOR_TEST，但不能标VERIFIED_RELEASE。测试命令返回0与业务必需A的PASS是不同条件。

状态枚举：PASS / FAIL / SKIPPED / BLOCKED / NOT_RUN。后四个均不是PASS。报告生成工具只有所有该scope必需A==PASS才exit0，否则exit2。

# 26. Golden Consumer / Real-world Acceptance

## 26.1 实体与记录

| 实体 | 记录内容 |
|---|---|
| `/data/projects/meeting-meeting` | 实际HEAD SHA、dirty、镜像digest、锁文件digest、配置摘要；本稿基线不代表现场已升级 |
| `/data/projects/meeting-integration-kit` | 实际工具版本/manifest、目标网关SHA、私有目录隔离 |
| 上游登录服务 | 用户指定精确URL；部署版本由运维记录，未知则注明未提供；不得增加接口获取版本 |
| 内部系统调用方 | 实际客户端ID、授予scope、调用入口版本；不记录client_secret |
| 账号A/B | 各自真实账号，不共用上游或本地Token；证据只保留本地非敏感引用 |
| 腾讯资源 | 经批准的非敏感已知会议/录制/纪要标识；样本对照证据受控存放 |

## 26.2 执行顺序

```text
只读检查本地版本/配置/业务摘要
→ 核验并备份旧映射与数据
→ 应用身份迁移，启动同epoch API/Worker
→ 操作员A通过网关账号登录（唯一上游POST）
→ 验证组织、稳定本地member_id与bootstrap资格
→ 配置客户端和有限会议权限
→ 用ms_交换REST mt_，确认后续请求无其他身份HTTP
→ 原AK/SK/OAuth连接按已授权范围读取腾讯会议结果
→ B通过自己的账号登录，验证无权限资源拒绝
→ 期限/本地撤销/健康与后台维护负向测试
→ 捕获零违规身份调用、记录真实结果、生成身份发布报告
```

首次没有B、没有既有样本、网络不可达或对应腾讯授权未开时，记录具体BLOCKED项，不自动新建测试会议或冒充B。真实CREATE、媒体下载和事件投递属于已批准业务scope的后续实测，不由本PRD自动授权执行。

## 26.3 单登录接口能做到与不能做到

可验证：此时账号能否登录、返回组织是否匹配、网关是否仅使用本地身份、权限是否隔离、是否确实没有禁止网络调用。

不能凭这份响应证明：未来某分钟上游账号已停用、未返回部门和完整通讯录、上游被隐藏的强制改密状态、对方已撤销所有历史JWT。需要重新观察时只能由用户主动再次account-login；本地紧急禁用即时阻断本地后续授权，但不代替上游全局登出。

# 27. Requirement Traceability Matrix

| Requirement | Invariant | Acceptance | Test | Evidence | Release Gate |
|---|---|---|---|---|---|

| REQ-API-001 | INV-API-001 | A-API-001-01<br>A-API-001-02 | TEST-A-API-001-01<br>TEST-A-API-001-02 | EVID-A-API-001-01<br>EVID-A-API-001-02 | IDENTITY-CODE / REQUIRED |

| REQ-CONFIG-001 | INV-CONFIG-001 | A-CONFIG-001-01<br>A-CONFIG-001-02 | TEST-A-CONFIG-001-01<br>TEST-A-CONFIG-001-02 | EVID-A-CONFIG-001-01<br>EVID-A-CONFIG-001-02 | IDENTITY-CODE / REQUIRED |

| REQ-API-002 | INV-API-002 | A-API-002-01<br>A-API-002-02 | TEST-A-API-002-01<br>TEST-A-API-002-02 | EVID-A-API-002-01<br>EVID-A-API-002-02 | IDENTITY-CODE / REQUIRED |

| REQ-IDENTITY-001 | INV-IDENTITY-001 | A-IDENTITY-001-01<br>A-IDENTITY-001-02 | TEST-A-IDENTITY-001-01<br>TEST-A-IDENTITY-001-02 | EVID-A-IDENTITY-001-01<br>EVID-A-IDENTITY-001-02 | IDENTITY-CODE / REQUIRED |

| REQ-AUTH-001 | INV-AUTH-001 | A-AUTH-001-01<br>A-AUTH-001-02 | TEST-A-AUTH-001-01<br>TEST-A-AUTH-001-02 | EVID-A-AUTH-001-01<br>EVID-A-AUTH-001-02 | IDENTITY-CODE / REQUIRED |

| REQ-AUTH-002 | INV-AUTH-002 | A-AUTH-002-01<br>A-AUTH-002-02 | TEST-A-AUTH-002-01<br>TEST-A-AUTH-002-02 | EVID-A-AUTH-002-01<br>EVID-A-AUTH-002-02 | IDENTITY-CODE / REQUIRED |

| REQ-SEC-001 | INV-SEC-001 | A-SEC-001-01<br>A-SEC-001-02 | TEST-A-SEC-001-01<br>TEST-A-SEC-001-02 | EVID-A-SEC-001-01<br>EVID-A-SEC-001-02 | IDENTITY-CODE / REQUIRED |

| REQ-DATA-001 | INV-DATA-001 | A-DATA-001-01<br>A-DATA-001-02 | TEST-A-DATA-001-01<br>TEST-A-DATA-001-02 | EVID-A-DATA-001-01<br>EVID-A-DATA-001-02 | IDENTITY-CODE / REQUIRED |

| REQ-RUNTIME-001 | INV-RUNTIME-001 | A-RUNTIME-001-01<br>A-RUNTIME-001-02 | TEST-A-RUNTIME-001-01<br>TEST-A-RUNTIME-001-02 | EVID-A-RUNTIME-001-01<br>EVID-A-RUNTIME-001-02 | IDENTITY-CODE / REQUIRED |

| REQ-TXN-001 | INV-TXN-001 | A-TXN-001-01<br>A-TXN-001-02 | TEST-A-TXN-001-01<br>TEST-A-TXN-001-02 | EVID-A-TXN-001-01<br>EVID-A-TXN-001-02 | IDENTITY-CODE / REQUIRED |

| REQ-MIGRATE-001 | INV-MIGRATE-001 | A-MIGRATE-001-01<br>A-MIGRATE-001-02 | TEST-A-MIGRATE-001-01<br>TEST-A-MIGRATE-001-02 | EVID-A-MIGRATE-001-01<br>EVID-A-MIGRATE-001-02 | IDENTITY-CODE / REQUIRED |

| REQ-SEC-002 | INV-SEC-002 | A-SEC-002-01<br>A-SEC-002-02 | TEST-A-SEC-002-01<br>TEST-A-SEC-002-02 | EVID-A-SEC-002-01<br>EVID-A-SEC-002-02 | IDENTITY-CODE / REQUIRED |

| REQ-SEC-003 | INV-SEC-003 | A-SEC-003-01<br>A-SEC-003-02 | TEST-A-SEC-003-01<br>TEST-A-SEC-003-02 | EVID-A-SEC-003-01<br>EVID-A-SEC-003-02 | IDENTITY-CODE / REQUIRED |

| REQ-CHECK-001 | INV-CHECK-001 | A-CHECK-001-01<br>A-CHECK-001-02 | TEST-A-CHECK-001-01<br>TEST-A-CHECK-001-02 | EVID-A-CHECK-001-01<br>EVID-A-CHECK-001-02 | IDENTITY-CODE / REQUIRED |

| REQ-UI-001 | INV-UI-001 | A-UI-001-01<br>A-UI-001-02 | TEST-A-UI-001-01<br>TEST-A-UI-001-02 | EVID-A-UI-001-01<br>EVID-A-UI-001-02 | IDENTITY-CODE / REQUIRED |

| REQ-INTEGRATION-001 | INV-INTEGRATION-001 | A-INTEGRATION-001-01<br>A-INTEGRATION-001-02 | TEST-A-INTEGRATION-001-01<br>TEST-A-INTEGRATION-001-02 | EVID-A-INTEGRATION-001-01<br>EVID-A-INTEGRATION-001-02 | IDENTITY-CODE / REQUIRED |

| REQ-EVID-001 | INV-EVID-001 | A-EVID-001-01<br>A-EVID-001-02 | TEST-A-EVID-001-01<br>TEST-A-EVID-001-02 | EVID-A-EVID-001-01<br>EVID-A-EVID-001-02 | IDENTITY-CODE / REQUIRED |

| REQ-REGRESSION-001 | INV-REGRESSION-001 | A-REGRESSION-001-01<br>A-REGRESSION-001-02 | TEST-A-REGRESSION-001-01<br>TEST-A-REGRESSION-001-02 | EVID-A-REGRESSION-001-01<br>EVID-A-REGRESSION-001-02 | IDENTITY-CODE / REQUIRED |

| REQ-CMD-001 | INV-CMD-001 | A-CMD-001-01<br>A-CMD-001-02 | TEST-A-CMD-001-01<br>TEST-A-CMD-001-02 | EVID-A-CMD-001-01<br>EVID-A-CMD-001-02 | IDENTITY-CODE / REQUIRED |

| REQ-GOLDEN-001 | INV-GOLDEN-001 | A-GOLDEN-001-01<br>A-GOLDEN-001-02 | TEST-A-GOLDEN-001-01<br>TEST-A-GOLDEN-001-02 | EVID-A-GOLDEN-001-01<br>EVID-A-GOLDEN-001-02 | IDENTITY-LIVE / REQUIRED |

所有Normative ID继承本行REQ对应的正向/负向A，不存在未映射的MUST。某个A涉及多个边界时，以第21章参数化输入矩阵和第23章注入点逐项展开，不能只运行一个分支。

# 28. Plan Generation Contract

本稿为REVIEW。只有用户/责任人将**本版具体文档**批准为APPROVED_FOR_PLAN后，才可输出实施`.plan.md`。本轮不生成代码或计划，不修改服务器配置。

计划入口检查：每个REQ有正负A、错误、所有权、事务范围、可观察oracle；所有新配置有默认/范围/缺失行为；所有当前源码改造有符号定位；所有真实环境未知值作为环境输入，不由开发Agent伪造。

发现未定义字段、组件语义与现有企业平台冲突、或现场account-login请求与本合同不兼容时，返回SPEC_SEMANTIC_GAP。不要通过增加被禁止的接口填平缺口。新的target SHA尚未产生不是语义缺口，发布工具在实现提交后记录实际值，不写假的SHA。

# 29. `.plan.md` 输出标准

计划Todo逐项使用以下字段，不把本文的设计状态当成实现状态：

```yaml
id: PLAN-IDENTITY-001
requirement_refs: [REQ-API-001]
acceptance_refs: [A-API-001-01, A-API-001-02]
files_or_symbols: [app/integrations/account_login/client.py, app/runtime.py]
implementation_goal: "唯一账号登录出站与旧身份调用移除"
preconditions: "本PRD已APPROVED_FOR_PLAN，基线与目标分支已核对"
state_transition: "旧Backend解析 -> 本地会话与登录单入口"
side_effect_scope: "限定仓库文件；不访问真实登录/腾讯"
failure_cases: "重定向、HTTP例外关闭、代理、旧调用路径"
verification: "逐A测试命令与oracle"
status: planned
evidence: []
commit_policy: post_review
```

`implemented`表示代码写入；`verified`表示对应A已有本target SHA的证据。依赖上游身份网络的旧测试要换为真实本地会话fixture，不是删除授权断言。

# 30. Code Review Contract

Review顺序：REQ覆盖 → 身份SOT → 出站集合 → 本地/腾讯主体边界 → 事务与失效 → 旧ID迁移 → 安全日志 → AC实际覆盖 → 真实Evidence → 可维护性。

重点查看：

- 是否只在adapter改了URL，却遗漏AuthService、TencentClient、Worker、订阅、health与旧安装脚本。
- 是否把`lookup_local_member`的存在性当成当前用户已认证，或用一名公共管理员绕过成员检查。
- 是否使用上游JWT decode代替直接登录观察；是否会保存refresh_token继续访问上游刷新。
- 是否错误把`role=user`盖过`portal_org_role=admin`，或让`is_task_admin`授会议正文权。
- 是否新登录自动覆盖local_disabled、刷新无限延期、旧作业在父身份过期后发腾讯创建。
- 是否迁移未覆盖关联历史ID而把旧权限重新授给UUID相似的新用户。
- 是否把账号服务HTTP明文例外描述成已经具备TLS；是否在调试日志泄露密码或上游Token。

# 31. PRD Quality Gate

| 维度 | 本文覆盖位置 | 文档状态 |
|---|---|---|
| 唯一目标、边界与Owner | 0—6章 | 已定义 |
| SOT/状态机/角色与期限 | 7—9章 | 已定义 |
| 输入默认值、组织/组件语义 | 5、9章 | 已定义；为本次设计，待本版审批 |
| 规范、错误与正负向验收 | 9.7、10、20—23章 | 已定义 |
| side effect/ownership/hash/事务 | 11—15章 | 已定义 |
| 迁移和旧会话处理 | 16章 | 已定义 |
| 依赖版本及资料限制 | 17章 | 固定网关SHA；上游现场版本未验证 |
| 安全与证据 | 18—27章 | 已定义；不是执行成功记录 |
| 模板0—36章节与引用结构 | 本文件结构检查 | 生成后由校验脚本给出实际结果 |
| APPROVED_FOR_PLAN | 元数据 | 未批准：REVIEW |
| IMPLEMENTED/VERIFIED | 代码/现场 | 本轮未实施、未验证 |

# 32. PRD 禁止写法

| 不采用的表述 | 本稿明确语义 |
|---|---|
| “只换一个登录地址就行” | 删除整个运行时旧context/resolve/search/health调用链 |
| “组件ID就是组织ID” | MEETING_COMPONENT_ID与MEETING_ORG_ID分别定义并校验 |
| “收到JWT就知道是谁” | 固定上游直接登录结果→本地会话，旧JWT本身不作为认证 |
| “缓存员工就是实时校验” | 观察只代表登录时刻；本地固定租期与撤销负责后续边界 |
| “admin有所有会议权限” | 初始管理资格与会议业务grant分离 |
| “测试通过就能上线” | 全部Required A、真实消费者和禁止HTTP计数都有Evidence才PASS |
| “回滚恢复一切” | 本地受管事务回T0；上游登录及已发送腾讯操作不可宣称回滚 |

# 33. 推荐 ID 体系

本文采用：`REQ-<领域>-<三位编号>`、`REQ-...-Nxx`、`INV-...`、`A-<领域>-<三位编号>-<两位case>`、`TEST-A-...`、`EVID-A-...`、`FI-xx`。

`application_id/connection_id/member_id/user_id/component_id/org_id`在API、日志、文档中保持不同字段；不使用无类型的“ID”代替。日志中的actor指内部调用主体，operator指腾讯操作者，二者不能互相填入。

# 34. PRD 最小完整结构

本稿保留模板第0—36章，不只填最小章节。最小合同的对应位置为：Goal(2)、Scope(4)、State(7—8)、Schema(9)、Requirements(10)、Side-effect(11)、Ownership(12)、Identity/Hash(13)、Transaction/Failure(14/23)、Migration(16)、Security(18)、Acceptance(20—22)、Evidence/Traceability(24/27)、Gate(25/28)、DoD(35)。

# 35. Definition of Done

## 35.1 文档进入计划

文档结构完整、全部Normative ID可追踪、所有默认值/失败/身份映射/租期已定义、资料支持范围写清；用户批准本版并将状态变更为APPROVED_FOR_PLAN。当前仅到REVIEW，不自动替用户批准。

## 35.2 代码交付

新的账号登录模式、LocalMember/Session、原业务身份调用替换、迁移命令、配置、installer、页面/CLI、kit、Hermes指令全部有实际实现；仓库扫描和运行时捕获的禁止身份请求数均为0；密码/Token泄露探针为0；全部合成/负向/并发/迁移回归证据可复验。

## 35.3 现场发布

在指定服务器完成真实account-login、env组织匹配、内部客户端交换、原已授权腾讯资源访问及B负向；保存实际代码SHA/配置摘要/命令/结果。远端账号状态不可实时观测的限制、HTTP明文内网例外和未执行的业务写测试在报告中明示。任一必需A未PASS则不可标记VERIFIED_RELEASE。

# 36. 最终原则

1. 身份服务只在用户主动登录时调用account-login，其余认证与成员查询在网关本地完成。
2. 组件ID、组织ID、外部用户ID、本地成员ID、腾讯企业与应用ID分别管理。
3. 登录成功不是会议权限授权，也不是上游员工未来状态的实时证明。
4. 既有业务接口、腾讯授权和人工确认的边界不因身份来源调整而放宽。
5. 无法从单登录接口得到的信息明示缺失，不调用禁止接口补全，不以假数据填充。
6. 本PRD是改造合同；未实施、未联调、缺Evidence都不能标记通过。
