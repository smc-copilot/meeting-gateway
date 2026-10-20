---
title: "nodeskclaw-meeting：腾讯会议接入与内部系统接口网关解决方案 PRD"
subtitle: "面向内部应用服务器的 REST / MCP 双入口工程需求合同"
prd_id: "PRD-MEETING-GATEWAY-001"
version: "1.0"
template_version: "1.0"
status: "APPROVED_FOR_PLAN"
prd_digest: "73a7226d0fb3feda82f7a5fb89a3594a6fa2b9ef6a11e7702a0178ae1b06bd34"
product: "nodeskclaw-meeting"
repository: "https://github.com/loudon84/nodeskclaw"
base_commit: "83edfb0d97f07920deb8bb9ce44a91e3e32cc3af"
branch: "feat/meeting-internal-gateway"
owner: "需求提出方及其指定产品负责人"
reviewers: ["内部系统接口负责人", "Backend 身份负责人", "Meeting 开发负责人", "安全与运维负责人"]
created_at: "2026-10-16"
updated_at: "2026-10-16"
phase1_decisions: "0.4"
target_release: "1.0.0rc2"
change_type: ["BROWNFIELD_CHANGE", "INTEGRATION", "NEW_FEATURE", "BUGFIX", "MIGRATION"]
golden_consumer: "由 deploy/bindings/golden-consumer.json 标识的真实内部应用服务器；绑定规则见第26章"
related_docs:
  - "需求PRD工程模板.md"
  - "nodeskclaw-meeting-v1.0.0-rc1-source.zip"
  - "nodeskclaw-meeting-v1.0-design.md"
  - "nodeskclaw-meeting-rc2-integration-checklist.md"
supersedes:
  - "原设计中将 Meeting Portal 作为员工创建与业务确认必经入口的要求"
  - "原设计中以先全量同步本地目录作为内部系统查询腾讯会议前提的要求"
---

# nodeskclaw-meeting：腾讯会议接入与内部系统接口网关解决方案 PRD

> 交付目标：内部系统调用 Meeting 接口，Meeting 对接腾讯会议；员工继续在原内部系统工作。
>
> 本稿是可供评审的需求合同，不是源码、实施计划或腾讯联调通过报告。`REVIEW` 不代表已获用户批准，也不代表代码已实现。本稿新增的默认值、请求字段、状态与安全策略均为本次设计决策，不冒充现有代码行为或腾讯官方限制。

# 0. PRD 使用原则

## 0.1 PRD 的职责

本 PRD 的唯一业务主线是：**腾讯会议应用接入 → 内部调用方认证与员工权限 → 创建/查询会议 → 取得原生会议结果 → 向内部系统交付数据与事件**。MCP 是同一能力的协议入口，不是另一套业务平台。

文档区分四类依据：

| 标记 | 含义 | 使用限制 |
|---|---|---|
| USER | 当前对话明确的目的和已确认边界 | 优先于旧设计中不一致的产品流程 |
| CODE | 本轮读取的 RC1 源码及包内记录 | 只说明代码存在和静态调用关系，不证明真实腾讯调用成功 |
| EXT | 本轮核对的腾讯/MCP 官方协议资料 | 仅约束相应外部契约，不替代企业实际授权结果 |
| DESIGN | 本稿为实现目标定义的字段、默认值、策略与验收 | 进入实施计划前由评审确认 |

WHY、WHAT、BOUNDARY、STATE、INPUT、OUTPUT、SIDE EFFECT、FAILURE、ACCEPTANCE、EVIDENCE 分别落实在第2—27章。协议与事务细节属于网关内部工程合同，不把这些复杂性转嫁给内部应用开发者。

## 0.2 强制规范关键词

`MUST`、`MUST NOT`、`SHOULD`、`SHOULD NOT`、`MAY` 沿用附件模板定义。第10章的每个规范子项标为 N1/N2/N3，并绑定 Acceptance；其他章节的合同由其“归属 Requirement”负责验收。第27章给出闭环，不以正文里出现一个关键词替代验收。

规范优先级：当前需求 USER → 第 0.4 节已确认的第一期裁决 → 本 PRD 已批准版本 → 本稿引用的固定外部协议配置 → 旧设计。第 0.4 节与后文 DESIGN 冲突时，以第 0.4 节为准。CODE 描述不是新的业务授权依据。遇到官方契约与本稿适配假设冲突时，返回外部契约错误并修订 PRD/适配配置，不静默换权限或更换数据来源。

## 0.3 No-Inference Rule

归属：REQ-GOV-001。无法唯一确定状态事实源、默认值、选择语义、权限范围、哈希、事务、冲突或 Oracle 时，报告 `SPEC_SEMANTIC_GAP` 并阻止生成计划。不得由开发 Agent 代选方案。

真实密钥、域名、员工 ID、测试会议 ID、内部消费方仓库 SHA 属于**部署输入**，其格式、获取责任和缺失行为已在第9、17、26章确定；缺失时是运行门禁 `DEPLOYMENT_BINDING_MISSING`，不得伪造数据，也不得标联调 PASS。

## 0.4 第一期已确认裁决

归属：REQ-GOV-001。2026-10-16 评审对话确认。标记为 USER。本稿状态为 APPROVED_FOR_PLAN，批准记录见第 1.2 节。未在下表改口的条款继续以原稿为准。企业时间窗、企业密钥通道、企业 STS、纯机器创建和代别人主持留待后续单独批准，不进入第一期发布门禁。

| ID | 裁决 |
|---|---|
| D-01 | 创建确认离开 Meeting Portal。第 9.4 节是创建权的唯一规则。Portal 只保留运维配置和诊断。需要人工确认时，确认发生在原内部系统。 |
| D-02 | 源查询与本地目录分成两套入口。后台全量同步不是查到一场会议的前提。 |
| D-03 | 转写和纪要的访问控制只在 Meeting 的授权与来源连接上。Backend 只核验员工是否有效。发现元数据和读取正文是两项权限。 |
| D-04 | 第一个内部系统的员工操作使用 TRUSTED_MEMBER，直接入队。纯机器代创建使用另行批准的 APPROVED_SERVICE。其余客户端保持 HUMAN_CONFIRM。 |
| D-05 | 第一期源查询只有 MEETING_ID 和 USER_WINDOW。CORP_WINDOW 第一期拒绝，且不发起上游调用。 |
| D-06 | 真实腾讯调用只能从已列入腾讯 IP 白名单的网关公网出口发起。开发机未获该授权。本机只跑合成传输。出口 IP 与消费方身份写入部署绑定，不写入本稿正文。绑定缺失时现场验收为 BLOCKED。 |
| D-07 | 第一期员工创建、按会议 ID 查询和成员时间窗只使用该员工自己的 THIRD_PARTY_OAUTH 连接。失败后不改用 ENTERPRISE_AKSK 或管理员身份重试。 |
| D-08 | 第一期创建的主持人必须是当前 Backend 已验证员工。on_behalf 与 APPROVED_SERVICE 第一期不实现。HUMAN_CONFIRM 的确认接口仍然实现，第一个接入系统不调用它。 |
| D-09 | 部署绑定完成前可以按本节编写和运行合成测试。第 26 章真实腾讯验收保持 BLOCKED。 |
| D-10 | USER_WINDOW 的 target_member_id 必须等于当前员工，连接必须是该员工自己的 OAuth 连接。替别人查或用系统身份查，第一期拒绝。 |
| D-11 | 按会议 ID 查询时，腾讯未返回，或 Meeting 授权没有该连接的发现权限，都返回 404 RESOURCE_NOT_ACCESSIBLE。不保存主题、会议号和入会链接。不使用企业管理员再查。 |
| D-12 | 第一期正文、纪要和受控下载只走该员工 OAuth 连接能读取的录制。企业 STS 申请、回调配对和票据注入不进入第一期。 |
| D-13 | 创建的 auto_record_type 默认 NONE，并明确传给腾讯为不录制。只有调用方显式传入 CLOUD 且组织已打开自动云录制时才传 cloud。第一期不接受 INHERIT、participant_join_auto_record、auto_asr。 |
| D-14 | 员工首次使用前的腾讯 OAuth 由原内部系统发起。Meeting 生成一次性 state，跳转腾讯，核对回调后回到已登记的内部地址。令牌不出现在浏览器地址中。Portal 不是第一个接入系统的绑定页。 |
| D-15 | 创建请求已经发往腾讯但没有明确结果时，操作停在 OUTCOME_UNKNOWN。同一 Idempotency-Key 只返回这笔操作，不自动再创建。只有确定未发出且腾讯明确拒绝时才算失败。 |
| D-16 | 会议详情、录制列表、转写和纪要在缓存缺失或过期时默认 ensure，返回 202 和作业。显式 fetch=cache 只读本地。GET /meetings 仍只表示已缓存目录。 |
| D-17 | 第一期对内签名事件只有创建结果和正文就绪。事件只含资源标识、版本和状态。不含正文、主持人姓名、分享密码或下载地址。腾讯入站回调的现场联调随 D-06 挂起。本机用合成上游验证签名、去重和撤权后停止投递。 |
| D-18 | MCP 调用与 REST 相同的业务服务和规则。智能体创建进入 HUMAN_CONFIRM，且不能调用确认接口。第一个真实内部系统走 REST。 |
| D-19 | 邀请人必须都在同一 OAuth 应用上完成身份映射。任一邀请人没有映射则整单拒绝。第一期仍不支持代替别人主持。 |
| D-20 | OAuth 刷新遇到超时、5xx 或分钟限额时保留已加密 refresh token，连接保持可恢复。只有刷新凭据被明确判定失效或撤销才进入重新授权。身份或返回结构不合法时阻断，原因不写成重新授权。 |
| D-21 | 下载只发放网关票据和网关地址。腾讯签名媒体地址不返回给内部系统。票据绑定当前主体。授权撤销后，新下载和未完成的 Range 续传都拒绝。 |
| D-22 | 会议详情和录制列表的 ensure 完成后只通过作业查询交付。不为元数据刷新另发事件。 |
| D-23 | HUMAN_CONFIRM 的确认期限为 10 分钟。超时后为 OPERATION_EXPIRED，不能再确认，也不能发给腾讯。TRUSTED_MEMBER 不进入这段等待。 |

# 1. 文档元数据

文首 YAML 为元数据事实源；本文重复展示的版本仅用于阅读，不允许单独修改。目标分支名称为建议工作分支，本文不声称已创建该分支。

| 元数据 | 值 |
|---|---|
| PRD 状态 | APPROVED_FOR_PLAN；批准记录见第 1.2 节 |
| 基础源码 | nodeskclaw-meeting-v1.0.0-rc1-source.zip |
| 仓库参考提交 | 83edfb0d97f07920deb8bb9ce44a91e3e32cc3af；来源为源码包 docs/PROVENANCE.md，不声称当前远端 HEAD 未变化 |
| 发布目标 | RC2 接口联调候选版，不等于生产正式上线 |
| 产品主消费者 | 真实内部应用服务器；智能体为另一类受限消费者 |
| 审批状态 | 需求提出方于 2026-10-16 要求按第 0.4 节收口并标记 APPROVED_FOR_PLAN。这不是执行 Evidence，也不表示真实腾讯联调已通过 |
| 变更边界 | 新增/调整 Meeting；Backend 仅身份与集成连接点；Portal 只保留运维辅助入口 |


### 1.1 输入材料完整性

| 材料 | SHA-256 | 本轮使用方式 |
|---|---|---|
| `需求PRD工程模板.md` | `b00234e6d103b2c102cbcc7b02fbcd961e71b0ce784ee736ead592c301e35eff` | 保留第0—36章顺序与工程合同要求 |
| RC1 源码 ZIP | `2449ce958dce10b07b5d66509623d13ccdc82207e4d16255e1f08180d4257b2f` | 解包只读检查，未改写源码 |

基础源码共有189个文件。数量是对输入 ZIP 的统计，不是本轮新交付代码数量。本轮未重新执行产品测试；历史报告中的测试结果不计为 RC2 验收证据。

### 1.2 批准记录

需求提出方在评审对话中确认第 0.4 节 D-01 至 D-23，并要求把 A-LIVE-001、A-LIVE-002、A-LIVE-003、REQ-EVID-001.N2、A-API-001-01 改成与第 0.4 节同一口径后，将本稿标为 APPROVED_FOR_PLAN。批准时间是 2026-10-16。批准范围是第一期计划合同，不包含真实腾讯联调 PASS，也不包含实施计划文件。

`prd_digest` 放在文首 YAML。校验时把该字段的 64 位 hex 换成 64 个 `0`，再对整个文件字节做 SHA-256，结果必须等于字段里的 hex。摘要使用小写。内容再改则状态回到 REVIEW，并重新计算摘要。


# 2. 一句话目标

让**已登记的内部应用服务器和获委托的智能体**，在**腾讯应用、调用方、员工身份及资源权限配置有效**的前提下，通过 **Meeting 提供的 REST API / MCP 与事件通知**，实现**创建、查询腾讯会议、获取录制/完整转写/腾讯原生纪要、下载授权资料并接收状态变化**，同时保证**不要求员工迁移到 Meeting 工作台、不泄露腾讯凭证、不跨身份越权、不因请求重试重复创建会议**。

# 3. 背景与问题定义

## 3.1 Current State

以下均为 USER/CODE 事实，代码位置以 RC1 ZIP 内 `nodeskclaw-meeting/` 为相对根：

| 事实 | 依据 |
|---|---|
| 用户已确认独立服务、Backend 身份来源、Meeting 权限执行及 OAuth/企业自建双通道 | 本对话确认内容 |
| `POST /api/v1/meetings` 当前总是调用 `operations.prepare()` | `app/api/business.py:27–29` |
| 创建参数检查直接拒绝 SERVICE 主体，并把创建记录置为 AWAITING_CONFIRMATION | `app/services/operation_service.py::_parameters / prepare` |
| `GET /meetings`、详情和录制列表读取本地 Meeting/Recording 记录 | `app/services/meeting_service.py::list / get / recordings` |
| 上游适配白名单已有 upcoming/history/records/corp_records/record_detail/transcript/minutes/create/sts，尚无独立的源会议查询能力 | `app/integrations/tencent_meeting/client.py:20–27` |
| 已有内部员工令牌兑换、client_credentials、OAuth 及 MCP 协议入口 | `app/services/auth_service.py`、`app/authorization/router.py`、`app/mcp/` |
| 已有 Tencent inbox、内部 outbox 和订阅授权复核 | `app/services/event_service.py`；不是从零开发消息模块 |
| 非 STS 事件主要使已有策略提前扫描；个人事件同步还依赖 PORTAL 客户端 | `app/services/event_service.py::process_inbox / _schedule_personal` |
| 默认限流间隔为0.2秒，拿不到额度即抛 RATE_LIMITED | `app/core/config.py`、`app/services/rate_service.py::acquire` |
| 先前离线报告记载分页未前进、临时刷新失败被标重新授权、错误分类不充分 | `meeting_review/offline-probe-results.json`；本轮引用报告，不声称重现已再次运行 |
| 架构与包布局参考 Knowledge/Task，精确依据在源码包来源说明 | `docs/PROVENANCE.md` |

## 3.2 Problem

P-01：内部系统提交创建后，无法按登记的机器调用策略直接进入执行，受到原 Portal 人工确认流程限制。

P-02：本地未同步的腾讯会议不能通过现有目录 API 直接发现，调用方被迫理解手工同步及导入步骤。

P-03：已有事件和内容处理不能充分保证“指定资源已可交付 → 精确通知订阅它的内部系统”，且有 Portal 耦合。

P-04：分页节流、令牌临时故障、上游错误分类会妨碍稳定交付会议结果；不能以增加工作台页面解决。

P-05：内部应用需要一套清晰的凭据兑换、授权、幂等、轮询和回调合同，而不是分别学习腾讯 AK/SK、OAuth、STS。

## 3.3 Impact

业务影响：员工被引导进入额外平台；内部系统不能直接获得可用的会议结果。

工程影响：不同内部系统重复实现腾讯身份、轮询及错误处理；已有 RC1 能力无法形成同一调用闭环。

安全影响：用企业管理员凭据查询成功容易被误解为所有员工都有权阅读；机器调用可能伪造员工或审批状态。

运维影响：收到腾讯事件、接口 HTTP 200、内容真正就绪三者易被混淆，失败难以定位。

AI Coding 影响：不明确创建执行策略、本地与上游查询差别及事务边界，Agent 会自行补成会议业务平台。

# 4. Scope

## 4.1 In Scope

| Scope ID | 交付范围 | Requirement |
|---|---|---|
| SCOPE-001 | 独立 Meeting 子项目与接口优先边界 | REQ-ARCH-001 |
| SCOPE-002 | 双应用配置与明确连接选择 | REQ-APP-001 |
| SCOPE-003 | 内部客户端、员工/系统身份、授权和映射 | REQ-AUTH-001、REQ-AUTH-002 |
| SCOPE-004 | 腾讯 OAuth 维护与 STS 生命周期 | REQ-AUTH-003、REQ-AUTH-004 |
| SCOPE-005 | 内部系统创建、源查询、详情与录制获取 | REQ-API-001、REQ-API-002、REQ-API-003 |
| SCOPE-006 | 完整转写、原生纪要和受控下载 | REQ-CONTENT-001、REQ-DOWNLOAD-001 |
| SCOPE-007 | 腾讯事件定向处理、对内签名通知 | REQ-EVENT-001、REQ-EVENT-002 |
| SCOPE-008 | 作业、分页进度、限流、重试、错误分类 | REQ-JOB-001 |
| SCOPE-009 | 自建 MCP 复用同一业务服务 | REQ-MCP-001 |
| SCOPE-010 | 最小运维配置、诊断与接入交付包 | REQ-OPS-001、REQ-DOC-001 |
| SCOPE-011 | 数据来源、事务、升级、安全和审计 | REQ-DATA-001、REQ-TXN-001、REQ-MIGRATE-001、REQ-SEC-001、REQ-OBS-001 |
| SCOPE-012 | 真实消费方、Evidence、发布和计划门禁 | REQ-EVID-001、REQ-GOV-001 |

## 4.2 Out of Scope

归属：REQ-ARCH-001、REQ-GOV-001；由 A-ARCH-001-02 / A-GOV-001-02 检查。

| Non-goal | RC2 明确不实施的内容 |
|---|---|
| NON-GOAL-001 | 不新建员工会议工作台，不要求业务创建必须访问 Meeting Portal |
| NON-GOAL-002 | 不实施会议申请审批、任务识别、OA 流程、翻译对比、知识库入库 |
| NON-GOAL-003 | 不重新开发 ASR、基础摘要、录制或参会客户端 |
| NON-GOAL-004 | 不实现周期会议、修改/取消/结束会议、会中控制、网络研讨会创建 |
| NON-GOAL-005 | 不进行应用市场上架、多外部企业商业化运营或会中 H5/JSAPI 发布；只保留扩展边界 |
| NON-GOAL-006 | 不依赖腾讯官方 Agent MCP 的灰度开通；RC2 MCP 上游使用已授权 REST 能力 |
| NON-GOAL-007 | 不提供任意 URL 代理、通用腾讯接口代签、原始凭据导出、任意 operator_id 参数 |
| NON-GOAL-008 | 不强制全企业历史录制归档，不以完成 Kubernetes 部署为接口联调前置条件 |

## 4.3 Architecture Boundary

| Domain | Owner | Input | Output | 不负责 |
|---|---|---|---|---|
| 需求 | 本 PRD 与产品评审人 | USER 目的、CODE/EXT 依据 | 版本化 REQ/AC | 自动宣布实现完成 |
| Spec | Meeting 领域契约维护人 | 已批准 PRD | OpenAPI/Schema/状态定义 | 擅自扩大范围 |
| Plan | 计划编制者 | APPROVED_FOR_PLAN PRD | 有 REQ/AC 引用的计划单元 | 补写缺失语义 |
| Execution | Meeting、Backend 增量开发者 | 已批准计划 | 代码、迁移、测试 | 主动写 OA、换全局登录 |
| Governance | Reviewer 与验收工具 | 代码与 Evidence | PASS/FAIL/BLOCKED | 把 SKIPPED 算 PASS |
| 内部业务 | 原内部应用服务器 | 员工业务操作或已批准任务 | 调用请求、展示与自身审批 | 持有腾讯密钥 |
| 身份 | Backend | 员工令牌、成员标识 | MemberContext | 判断某份纪要的访问 ACL |
| 会议网关 | Meeting | 已认证主体、连接、业务参数 | 会议资源、操作/作业状态、事件 | 重新执行内部系统业务审批 |
| 上游会议 | 腾讯会议 | 合法签名/API/OAuth 请求 | 外部会议状态与原生内容 | 内部员工权限策略 |

# 5. Terminology / Domain Model

| 术语 | 唯一定义 |
|---|---|
| Application / 腾讯应用 | 一组腾讯注册配置，类型为 ENTERPRISE_AKSK 或 THIRD_PARTY_OAUTH；不是内部客户端 |
| Connection / 腾讯连接 | 某应用下可执行操作的授权实例；企业连接与用户 OAuth 连接分开 |
| Client / 内部客户端 | 内部应用或 MCP 客户端的登记项，具有独立凭据和范围 |
| Principal / 调用主体 | 经认证得到的 MEMBER、SERVICE 或 AGENT，不接受请求体伪造 |
| Member | Backend 的 org membership，以 `(org_id, member_id)` 标识，不等于 user_id、腾讯 userid 或 open_id |
| Operator | 适配层根据已验证映射构造的腾讯操作者；不是对内可任意填写字段 |
| SOURCE 查询 | 通过已选 Connection 实际查询腾讯，可创建受控本地映射 |
| CATALOG 查询 | 只读本地已知会议目录，返回覆盖范围与采集时间，不代表腾讯全量 |
| Discovery Permission | 允许使用连接发现指定范围元数据；不自动授权读取所有发现结果的内容 |
| Operation | 具有外部业务副作用的创建操作日志；其成功须有腾讯结果或核对证据 |
| Job | 分页读取、内容获取、令牌维护或投递任务；受理不等于完成 |
| Ingestion / 采集 | 网关将经批准来源缓存到本地；不等于授权每个员工访问 |
| Origin / 来源 | 内容或会议通过哪条连接、什么授权依据获取；跨连接不自动合并权限 |
| READY | 网关已完成对应资源的读取/完整性检查，且可在权限范围内交付 |
| OUTCOME_UNKNOWN | 创建请求可能已到腾讯，但无法确认结果；不等于失败或可重试 |
| HUMAN_CONFIRM | 创建待经可信员工接口确认；确认页面属于原内部系统 |
| TRUSTED_MEMBER | 登记客户端代表经 Backend 验证的员工操作，可直接入执行队列 |
| APPROVED_SERVICE | 登记系统主体具有事先配置的连接、主持人和操作范围，可创建一次性会议 |
| Read-only upstream | 不改变腾讯业务源；本地审计、缓存与作业写入仍是副作用 |
| Implemented / Verified | 前者只有代码；后者具有对应 AC 执行 Evidence，两者不等价 |
| PASS / BLOCKED | 前者 Oracle 达成且证据齐备；后者因输入/环境/执行缺失无法验收，不是 PASS |

# 6. System Context

## 6.1 Context Diagram

```text
原内部应用服务器 ──员工令牌/机器凭据──┐
                                     ├── Meeting REST ─┐
获委托智能体 ──受限 MCP 凭据──────────┘                 │
                                  Meeting MCP ─────────┤
                                                       ▼
                                    统一认证 / 权限 / 业务服务
                                      │       │          │
                             Backend 身份   本地DB/作业   腾讯适配
                                                         │
                                          AK/SK+STS 或 OAuth
                                                         ▼
                                                    腾讯会议
                                                         │
原内部系统 ◀──签名事件/状态轮询── Outbox ◀── Worker ◀── Webhook
```

## 6.2 System Boundary

Inside boundary：应用与连接、内部客户端和委托、会议资源权限、源查询与映射、原生内容缓存、作业与事件、下载、审计、REST/MCP 适配。

Outside boundary：员工业务页面、原内部系统审批、OA/知识库任务、腾讯录制和智能处理、企业 SSO 账号源。

External dependency：Backend 身份 HTTP 服务、腾讯开放 API、PostgreSQL、私有存储、内部回调接收者。

Trusted input：经 Backend 确认的身份；经认证且版本匹配的策略；验签解密并关联成功的腾讯事件仅作为“上游观察”可信，不直接授予内部访问权限。

Untrusted input：普通请求体、用户给的员工 ID/腾讯 ID、会议正文、回调中业务字段、URL、MCP 工具参数及所有客户端自称已批准的字段。

# 7. Authoritative State / Source of Truth

归属：REQ-DATA-001、REQ-AUTH-002、REQ-TXN-001。下表覆盖全部持久状态类，持久化对象的实际物理表在迁移计划中映射，不另造事实源。

| State / 持久对象 | Role | Authoritative? | Writer | Reader | 可否自动覆盖 |
|---|---|---:|---|---|---|
| PRD版本与审批记录 | DESIRED_STATE | 是：范围语义 | 评审人 | 计划/验收工具 | 否 |
| Application配置、Client配置、组织保留策略 | DESIRED_STATE | 是：配置意图 | 授权管理员 | 适配/鉴权 | 仅版本匹配的显式更新 |
| IdentityBinding、AccessGrant、AgentGrant、ResourceACL | DESIRED_STATE | 是：内部授权 | 授权配置入口 | PermissionService | 否；腾讯回调不能授予权限 |
| Backend成员、组织启用状态 | OBSERVED_STATE | Backend是唯一事实源；Meeting不拥有账号 | Backend | Auth/Worker | Meeting只刷新观察，不修改Backend |
| Connection授权状态、OAuth票据、STS请求与票据 | OBSERVED_STATE | 是：最近确认的连接授权 | ConnectionService | 适配层 | 仅持锁且版本匹配的续期/撤销 |
| 腾讯会议/文件/转写/纪要 | OBSERVED_STATE | 腾讯业务事实源 | 腾讯 | 适配层 | 本地不能反向覆盖 |
| Meeting/Recording元数据、来源和健康时间 | OBSERVED_STATE | 是：所标时刻的缓存观察 | 源查询/内容/事件Worker | 业务接口 | 同来源较新已验证观察可更新 |
| Asset内容版本、paragraph片段、私有文件索引 | OBSERVED_STATE | 是：已获取版本；不是访问授权 | ContentService | 读取/下载 | 完整版本发布后不可原地改正文 |
| Principal、有效范围、选定连接与操作者 | RESOLVED_STATE | 仅本次决策有效 | Auth/Permission/Adapter | 本次操作 | 每次入口/执行重新计算 |
| 已迁移 schema版本、安装清单、legacy contract绑定 | LAST_APPLIED_STATE | 是：已应用版本 | 迁移/安装器 | drift检查 | 只随成功受管变更更新 |
| Operation、attempt、幂等记录、人工确认 | RUNTIME_STATE | 是：网关操作进度 | OperationService | 内部系统/Worker | 按合法状态机、CAS修改 |
| QueryRun、Job、checkpoint、lease、quota bucket | RUNTIME_STATE | 是：执行进度/调度 | JobService | Worker/状态API | 租约持有者按版本更新 |
| Subscription与Destination配置 | DESIRED_STATE | 是：通知目标和订阅意图 | 授权管理员/客户端配置入口 | EventService | 显式版本更新，不改历史投递快照 |
| Inbox、Outbox、Delivery | RUNTIME_STATE | 是：收发执行事实 | EventService | Worker/查询 | 按状态机更新，不用后来配置篡改历史记录 |
| 内部AccessToken/RefreshFamily、OAuth state/consent | RUNTIME_STATE | 是：票据与撤销状态 | AuthService | Auth/consent | 按单次消费和撤销语义更新 |
| DownloadTicket、DownloadSession、字节额度 | RUNTIME_STATE | 是：下载能力/计量 | DownloadService | 下载入口 | 到期/撤权后不可重新激活 |
| Audit、Trace、诊断结果、Evidence、digest manifest | EVIDENCE_STATE | 是：发生记录，不是业务授权 | 审计/测试工具 | Reviewer/运维 | 追加；内容保留按策略处理 |

状态优先级：组织/成员/客户端停用或 DENY → 当前内部授权 → 来源授权健康 → 腾讯资源观察 → 缓存内容。缓存存在不能覆盖当前 DENY；管理员配置权不能代替正文读取权。

# 8. State Machine

归属：REQ-AUTH-003/004、REQ-API-001/002/003、REQ-CONTENT-001、REQ-JOB-001、REQ-EVENT-001/002、REQ-TXN-001。未在下表列出的转移返回 `STATE_CONFLICT`，0目标状态变更。

| 对象/存储位置 | 合法转移 | 触发与前置条件 | 错误状态与恢复 |
|---|---|---|---|
| Application配置记录 | DISABLED → ENABLED → DISABLED | 管理员验证字段、凭据及版本后启用；禁用即阻止新上游调用 | 配置保存与探测成功分离；配置齐全不等于连通 |
| Client/Subscription配置 | DISABLED→ENABLED→DISABLED；任意有效态→REVOKED | 配置管理员或已获订阅管理权的客户端显式操作；必须If-Match | REVOKED终态；重新接入创建新记录，不恢复旧Token或积压投递 |
| Grant/AgentGrant/IdentityBinding | 授权PENDING→ACTIVE→REVOKED/EXPIRED；身份UNVERIFIED→VERIFIED→DISABLED | 只有授权人确认及可信身份校验能激活；到期由服务端时钟判断 | 被撤销授权不可直接ACTIVE；需新记录和新version；回调不能授予或修复权限 |
| OAuth State/Consent/AuthorizationCode | ISSUED→CONSUMED/DENIED/EXPIRED | state关联当前内部会话；授权码单次原子消费；员工确认只能改变其拥有的consent | 超时或重用拒绝；MCP不得调用授权确认接口批准自身 |
| OAuth Connection | PENDING_AUTH → ACTIVE；ACTIVE → DEGRADED → ACTIVE；ACTIVE/DEGRADED → REAUTH_REQUIRED → PENDING_AUTH；任意有效态 → REVOKED | OAuth身份和企业绑定核对成功；临时超时仅DEGRADED；明确刷新凭证失效才REAUTH_REQUIRED | ACTIVE/DEGRADED→BLOCKED_CONTRACT用于未知结构；BLOCKED_CONTRACT→ACTIVE仅经修订的固定适配合同重新验证成功；REVOKED不能直接改回ACTIVE，重新授权产生新连接版本 |
| STSRequest | REQUESTING → WAITING_CALLBACK → READY → EXPIRED；WAITING_CALLBACK → TIMED_OUT；任意进行态 → FAILED | req_id、应用、操作者和有效期均匹配；回调先到则放关联缓冲 | 300秒无匹配回调记TIMED_OUT；TIMED_OUT→READY仅在同req_id、同应用且票据未过期时允许；未知req_id不启用票据 |
| Operation | 新请求→AWAITING_CONFIRMATION或QUEUED；AWAITING_CONFIRMATION→QUEUED/REJECTED/EXPIRED；QUEUED→EXECUTING/REJECTED；EXECUTING→SUCCEEDED/FAILED/OUTCOME_UNKNOWN | 策略决定入队；确认需员工身份及request_hash匹配；执行前重验权限 | OUTCOME_UNKNOWN只允许LINK_VERIFIED_MEETING→SUCCEEDED或CLOSE_UNRESOLVED→CLOSED_UNRESOLVED；无自动再次创建 |
| Job/QueryRun | QUEUED→RUNNING→SUCCEEDED；RUNNING→WAITING_RATE/WAITING_CONTENT/RETRY_WAIT→QUEUED；RUNNING→FAILED/BLOCKED_AUTH；未开始→CANCELLED | 领取租约；执行及checkpoint由同一lease token提交 | 租约过期可重新领取读取任务；CREATE若已提交attempt走OUTCOME_UNKNOWN，不重发 |
| Content/Asset | ABSENT→FETCHING→READY/EMPTY/NOT_ENABLED；FETCHING→WAITING_CONTENT/FAILED/BLOCKED；READY→STALE→FETCHING；任意有效态→SOURCE_REMOVED | READY需完整页和类型验证、内容存储完成；原子切换版本 | 部分片段不对业务入口发布；旧版本不因新版本失败而改正文；撤权时阻止返回旧版 |
| Tencent Inbox | RECEIVED→PROCESSING→PROCESSED；RECEIVED→IGNORED；PROCESSING→RETRY_WAIT/FAILED；RETRY_WAIT→RECEIVED | 验签、解密、持久化后确认；未知事件忽略但记录脱敏类型 | 相同事件重复只确认既有记录；旧会议事件按目标资源处理，不靠两天窗口 |
| Internal Delivery | PENDING→SENDING→DELIVERED；SENDING→RETRY_WAIT→PENDING；任意未完成→SUPPRESSED/DEAD | 投递前重验订阅范围；2xx为接收成功 | 收件方响应丢失可能再次投递；使用相同event_id去重；撤权后SUPPRESSED |
| Download | ISSUED→ACTIVE→COMPLETED/EXPIRED/REVOKED | 首次开始60秒有效，活动会话最长3600秒，同主体和同内容版本 | 新请求/续传重新鉴权；已发送字节不可回收；中途撤权最多在下一复核点停止 |
| Evidence | BLOCKED→PASS/FAIL/SKIPPED | 有实际命令、exit code、Oracle、资源身份和文件digest | SKIPPED/BLOCKED均不满足Release Gate |

等待内容上限24小时；超时返回 `CONTENT_WAIT_TIMEOUT`，保留最后checkpoint和错误，允许新的明确读取请求。等待次数不计作网络错误重试。创建待处理确认10分钟到期；OAuth state/授权码使用第9章各自有效期。

# 9. Data / Schema Contract

## 9.1 Schema Rule

归属：REQ-DOC-001、REQ-DATA-001、REQ-GOV-001。RC2 对内合同版本为 `meeting.gateway/1.1`；旧内部接口合同以 `legacy/1.0` 保留。Schema采用 JSON Schema 2020-12，字段表给出必填项、默认、枚举及兼容规则。

所有本稿新增请求对象均 `additionalProperties=false`，未知字段返回422 `INVALID_REQUEST`。例外仅腾讯原始响应：适配器允许未知字段存在，但只映射本稿列出的字段，不把整个原响应透传。时间用带时区 RFC3339，入库 UTC；创建参数不接受小数秒，窗口按 `[start_at,end_at)`；外部ID均字符串，禁止转成浮点数。

省略值与显式null不同：表中有默认值才允许省略；标“可null”才接受null。枚举未知值不得自动选第一个；上游未知状态映射为UNKNOWN并保留不含敏感数据的诊断码。`meeting.gateway/1.1` 响应附 `contract_version`；`legacy/1.0` 保持RC1固定响应形状。新增字段需更新固定合同包，删除/改变已有字段需新主版本，不能把严格客户端破坏视为兼容。每个Client保存`contract_version`；旧客户端迁移为`legacy/1.0`，新客户端默认`meeting.gateway/1.1`。客户端API版本只允许在管理员显式更新并完成消费者合同验证后切换，不按请求成败自动选择版本；已建立订阅的版本冻结，转换需新建订阅。

### 9.1.1 Schema 注册表

| Schema ID（版本1.1，另标除外） | 用途 | Authority | 迁移/兼容 |
|---|---|---|---|
| S-APP | 腾讯应用配置 | 管理员 | RC1字段不改名，新增探测和版本字段 |
| S-CLIENT | 内部客户端配置 | 管理员 | 旧客户端create_policy默认HUMAN_CONFIRM |
| S-EXCHANGE | 员工令牌兑换 | 验证后的Backend上下文 | 保留RC1输入名称；拒绝自报member_id |
| S-PRINCIPAL | 服务端主体 | AuthService | 不对客户端开放写入 |
| S-GRANT / S-AGENT-GRANT / S-IDENTITY / S-ENTERPRISE-CONNECTION | 资源授权/委托/身份及企业连接 | 授权管理员/员工 | 新能力默认不自动授予旧授权 |
| S-CREATE | 一次性会议请求 | 内部调用方业务参数 | 新增录制参数；旧请求省略时继承腾讯配置 |
| S-QUERY | 腾讯源查询 | 请求+授权范围 | 新增，不改变旧GET目录语义 |
| S-MEETING | 会议元数据 | 腾讯观察+本地标识 | 标记source/observed_at，禁止虚构join_url |
| S-RECORDING | 录制元数据 | 腾讯观察 | 录制组、文件、会议ID分层 |
| S-CONTENT | 内容快照/分页 | 已发布Asset版本 | 新旧响应按合同绑定序列化 |
| S-CONFIRM | 确认请求 | 经验证员工 | approval_ref只审计，不是授权证明 |
| S-OPERATION | 创建状态 | Operation日志 | 保留RC1状态名与旧字段，新增execution_policy |
| S-JOB | 读取/投递进度 | 作业和checkpoint | 新增waiting_reason/results，不把排队标成功 |
| S-EVENT | 对内事件1.1 | Outbox | 旧事件名称通过订阅contract_version适配，不双发 |
| S-SUBSCRIPTION | 对内订阅 | 已授权客户端/管理员 | 目的地址只从注册allowlist选择 |
| S-DOWNLOAD | 下载许可与会话 | DownloadService | 保留RC1端点，同主体取文件 |
| S-ERROR | 公共错误包 | ErrorMapper | 旧numeric error_code保留；新增reason与上游脱敏码 |
| S-BINDING | 部署/Golden Consumer绑定 | 部署责任人 | 无默认账号/域名；缺失阻止对应运行门禁 |
| S-EVIDENCE | 验收证据，版本1.0 | 测试进程 | 完整定义见第24章 |

## 9.2 Field Semantic Table

### 9.2.1 公共字段与授权 DTO

| Schema.Field | Type | Required | Default | Authority | Meaning |
|---|---|---:|---|---|---|
| 通用.id | UUID字符串 | 响应是 | 服务器生成UUIDv4 | Meeting | 网关资源标识，不是腾讯ID |
| 通用.org_id | string≤64 | 服务端是 | 无 | Backend/客户端绑定 | 不接收普通业务请求指定 |
| 通用.version | int≥1 | 持久记录是 | 1 | 本地写者 | 更新使用If-Match；不以last-writer-wins覆盖 |
| S-APP | 继承RC1 ApplicationCreate全部字段 | 是 | RC1默认 | 管理员 | 应用类型与密钥字段互斥；禁用不删除已用密钥版本 |
| S-APP.enabled | bool | 否 | false（新增配置） | 管理员 | 探测可针对DISABLED配置显式运行；业务调用仍禁止 |
| S-CLIENT | 继承RC1 ClientCreate字段 | 是 | RC1默认 | 管理员 | client_type为CONFIDENTIAL或PUBLIC_MCP |
| S-CLIENT.create_policy | enum | 否 | HUMAN_CONFIRM | 管理员 | HUMAN_CONFIRM/TRUSTED_MEMBER/APPROVED_SERVICE |
| S-CLIENT.allowed_connection_ids | string[]去重≤100 | 是 | 无 | 管理员 | 空数组=无连接权限，不是全连接 |
| S-CLIENT.confirming_client_ids | string[]去重≤20 | 否 | [] | 管理员 | 被允许代表确认人的内部应用；同client自动允许，跨client需显式登记 |
| S-CLIENT.consent_client_id | string≤64，可null | 否 | null | 管理员 | MCP需要交互授权时对应的可信内部Web后端；不设则交互授权不可用 |
| S-CLIENT.consent_uri | HTTPS字符串≤1024，可null | 否 | null | 管理员 | 内部系统承载授权确认的地址；精确登记且禁止开放重定向 |
| S-EXCHANGE.client_id/client_secret | string≤64/512 | 是 | 无 | 已注册客户端 | 保留POST /api/v1/auth/exchange；密钥只在内部后端 |
| S-EXCHANGE.subject_token | string≤8192 | 是 | 无 | Backend验证 | 现有Backend可识别的员工令牌；不是腾讯Token |
| S-EXCHANGE.scopes | string[]去重≤30 | 是 | 无 | 请求范围∩授权 | 请求超出client范围直接拒绝，不默默扩权 |
| S-EXCHANGE.resource | HTTPS URI≤512 | 是 | 无 | 精确受众 | REST和MCP受众分离 |
| S-PRINCIPAL | org_id,client_id,actor_type,member_id,user_id,agent_id,agent_grant_id,token_id,audience,scopes,policy_version | 条件必填 | 无 | AuthService | MEMBER必须member_id；SERVICE不得伪造member_id；AGENT必须成员和委托 |
| S-GRANT | RC1 GrantCreate / AgentGrantCreate字段 | 是 | RC1默认但新能力空 | Meeting权限 | 新增meeting.query.source、meeting.create.service；创建SERVICE需host白名单 |
| S-GRANT.scope_type | enum | 是 | 无 | 管理员 | SELF_CREATED/EXPLICIT/ORG_APPROVED/PARTICIPATED；参与范围不自动授予正文/下载 |
| S-GRANT.connection_ids | string[] | 是（RC2新建授权） | 无 | 授权者 | 空=无连接；旧空数组的迁移见第16章，不继承为无限范围 |
| S-GRANT.target_member_ids | string[] | 代创建/机器创建是 | []（其他） | 授权者 | SERVICE创建必须非空且主持人属于该表 |

票据默认：网关access token 900秒；refresh family 7天；授权码60秒且单次消费；Backend成员上下文缓存TTL=0。系统client_credentials不返回refresh token。实际有效scope为客户端、成员/系统授权、智能体委托交集；无匹配或命中DENY拒绝。

### 9.2.2 创建与确认

| Field | Type | Required | Default | Authority | Meaning |
|---|---|---:|---|---|---|
| S-CREATE.subject | string | 是 | 无 | 业务输入 | strip首尾空白后1–256个UTF-16 code units，不折叠内部空白 |
| start_at/end_at | RFC3339秒精度 | 是 | 无 | 业务输入 | start_at在受理时晚于当前时间，end_at>start_at；执行时会议已结束则拒绝 |
| host_member_id | string≤64 | 是 | 无 | 可信员工映射 | 不接受任意腾讯主持人ID |
| invitee_member_ids | string[]≤300 | 否 | [] | 业务输入+Backend映射 | 去重不靠自动丢弃：重复输入422；映射缺失不静默漏邀请 |
| connection_ref | string≤64 | 是 | 无 | 经授权选择 | 单一连接，不按成功率切换 |
| business_ref | string≤128，可null | 否 | null | 内部系统 | 关联其业务记录，不能据此获得授权 |
| auto_record_type | NONE/CLOUD | 否 | NONE | 显式业务输入+组织开关 | 见 D-13。默认 NONE 并传给腾讯不录制；CLOUD 仅在显式传入且组织已打开自动云录制时传 cloud。第一期拒绝 INHERIT、participant_join_auto_record、auto_asr 和 LOCAL |
| S-CONFIRM.request_hash | lowercase hex64 | 是 | 无 | Operation参数摘要 | 对冻结参数确认，修改参数须新操作 |
| S-CONFIRM.approval_ref | string≤128，可null | 否 | null | 内部流程标识 | 仅审计；是否允许确认由当前员工、客户端、归属与策略决定 |

请求header `Idempotency-Key` 必填，1–128可打印ASCII字符，无前后空格。客户端不得传 `operator_id`、`execution_policy`、`approved=true`、腾讯密钥或任意上游settings对象。企业录制锁定冲突不静默改成另一录制方式。[EXT-03]

### 9.2.3 SOURCE 查询与本地读取

| Field | Type | Required | Default | Authority | Meaning |
|---|---|---:|---|---|---|
| S-QUERY.connection_ref | string≤64 | 是 | 无 | 调用者授权 | 选定单一授权连接 |
| selection | MEETING_ID/USER_WINDOW/CORP_WINDOW | 是 | 无 | 业务输入 | 查询语义互斥，不推断。第一期只接受 MEETING_ID 与 USER_WINDOW；CORP_WINDOW 按 D-05 拒绝且 0 上游调用 |
| provider_meeting_id | string≤128 | MEETING_ID是 | 其他必须省略 | 腾讯ID | 不能用九位meeting_code代替 |
| target_member_id | string≤64 | USER_WINDOW是 | 其他必须省略 | Backend身份映射 | 见 D-10。第一期必须等于当前员工，且连接是该员工自己的 OAuth 连接 |
| state | UPCOMING/ONGOING/ENDED | 窗口查询是 | MEETING_ID省略 | 业务输入 | 一次一种状态，无隐含ALL |
| start_at/end_at | RFC3339秒精度 | 窗口查询是 | MEETING_ID省略 | 业务输入 | end>start，单次≤31天；这里31天是网关统一约束，不宣称所有腾讯接口相同 |
| limit | int 1–100 | 否 | 20 | 业务输入 | 返回授权后的最多条数 |
| cursor | string≤4096，可null | 否 | null | 服务器签发 | 原查询、主体、连接、策略版本绑定；不可改变选择条件 |
| GET fetch | cache/ensure | 否 | ensure | 接口参数 | 见 D-16。省略或 ensure：缓存新鲜返回 200，缺失或过期返回 202。显式 cache 只读本地 |
| GET max_age_seconds | int 0–300 | 否 | 60 | 接口参数 | 只对ensure生效，0要求新上游观察；cache时提供则422 |

SOURCE查询统一202返回job_id；`GET /jobs/{id}`成功结果为 `{items,next_cursor,observed_at,source_scope,has_more}`，不额外引入查询工作台。最多扫描5个上游页或返回limit条后交回cursor；不足一页但扫描预算耗尽允许空items+非空cursor。每个上游页先过滤授权再发布/缓存；游标绑定实际扫描位置而不是未经授权行数。腾讯不提供全局快照的接口不被包装成强一致历史快照。

MEETING_ID要求已授予连接发现范围，并使用 D-07 的员工 OAuth 连接。腾讯未返回，或不属于授权范围时，返回404 `RESOURCE_NOT_ACCESSIBLE`，不持久化主题、会议号、入会链接或正文，也不改用企业管理员重试（D-11）。窗口过滤按会议计划开始时间落在半开区间；上游不能过滤的条件在网关过滤。记录每页观察时间，空列表只表示本次范围为空。

### 9.2.4 输出、资源和事件

| Schema.Field | Type / Required / Default | Authority / Meaning |
|---|---|---|
| S-MEETING | id、connection_ref、provider_meeting_id、subject、state、version、source、observed_at必填；meeting_code/start_at/end_at/host_member_id/join_url可null | 上游未返回入会链接时保持null，不自行拼装；source为TENCENT_API/CACHE |
| S-RECORDING | id、meeting_id、recording_group_id、provider_record_file_id、state、assets必填；start_at/end_at/size_bytes可null | 1场会议可有多个组和文件；元数据接口不含原始下载URL |
| S-CONTENT | asset_id、recording_id、asset_type、state、is_complete、version、observed_at、source、content_digest必填；body/paragraphs/next_cursor条件返回 | asset_type为transcript/minutes；只有READY或明确EMPTY交付正文；未知总量为null |
| S-CONTENT.paragraphs[] | pid字符串、start_ms/end_ms非负整数、speaker_name可null、text字符串 | 按腾讯顺序；未知发言人不按姓名映射员工权限 |
| S-CONTENT.minutes_profile | `{llm:3,text_type:1,minute_type:null}` | RC2固定元宝Markdown合同；不从另一模型/本地LLM补缺失摘要 |
| S-OPERATION | id、state、request_hash、request、execution_policy、created_at、updated_at必填；meeting_id、job_id、last_reason、confirm_deadline、approval_ref可null | HTTP202和QUEUED不等于腾讯创建成功 |
| S-JOB | id、kind、state、created_at、updated_at、attempt_count、wait_count必填；waiting_reason、retry_at、checkpoint_summary、result、error可null | result按kind为会议查询/刷新/内容/投递结果；不含令牌和原始请求正文 |
| S-DOWNLOAD | ticket、download_path、start_before、session_expires_at、asset_id、version、requires_authorization必填 | 相对网关路径；requires_authorization始终true；同主体持Bearer取文件 |
| S-EVENT | contract_version、event_id、event_type、resource_type、resource_id、resource_version、occurred_at、observed_at、connection_ref、trace_id必填；operation_id/business_ref/error_reason可null | 事件仅必要标识，不含正文、主持人姓名、分享密码或签名下载URL |
| S-SUBSCRIPTION | client_id、destination_ref、event_types、connection_ids、contract_version必填；resource_ids默认[]表示该连接内当前授权资源 | destination_ref引用管理员登记的URL；空connection_ids=无范围；旧destination迁移见第16章 |
| S-ERROR | code、error_code、reason、message_key、message、trace_id、data必填；data含retryable和retry_after_seconds（可null） | 现有error_code数字映射留存；新增reason为稳定字符串；没有错误时data为业务结果 |
| S-BINDING | consumer_repo、consumer_commit、backend_url、gateway_url、org_id、client_id、member_a、member_b、connection_refs、known_meeting_id、known_record_file_id、event_receiver_ref必填 | 不包含密钥；credentials通过secret_ref；缺任何必填项阻止相应live测试 |

所有业务响应 envelope 保留RC1 `code/error_code/message_key/message/data`，新增可选contract_version/trace_id按客户端合同序列化。OAuth标准端点保持OAuth错误格式；MCP外层保持JSON-RPC，业务错误放tool result，不能硬套REST envelope替代协议。


### 9.2.5 响应字段类型与空值补充

归属：REQ-DOC-001、REQ-DATA-001；由A-DOC-001-01/02、A-DATA-001-01/02校验。下表补足上一表的共同类型，不能由客户端猜测省略值。

| 字段类别 | 类型、默认及边界 |
|---|---|
| 资源id、connection_ref、resource_id | 服务器UUID字符串，必填不为空；provider标识为1–128字符字符串 |
| version、resource_version | 整数≥1；新版本初始1，只有内容/业务状态发生可观察变化才递增 |
| created_at、updated_at、occurred_at、observed_at | UTC RFC3339字符串；必填项禁止null，响应时间允许微秒；不使用客户端时间覆盖上游事实时间 |
| S-MEETING.state | UPCOMING / ONGOING / ENDED / CANCELLED / UNKNOWN；上游状态无法映射时为UNKNOWN，不默认ENDED |
| S-RECORDING.state | PROCESSING / READY / FAILED / UNKNOWN / SOURCE_REMOVED；READY表示录制文件可读取，不代表转写和纪要可读 |
| S-CONTENT.state | 使用第8章Content状态枚举；未发布内容的body、paragraphs、content_digest为null；READY的digest必填hex64；EMPTY的body为""、paragraphs为[]且有空内容digest |
| S-CONTENT.is_complete | bool；READY/EMPTY为true；FETCHING/WAITING_CONTENT/FAILED/BLOCKED等未完成状态为false；分页只在已完整发布版本上执行 |
| S-CONTENT.version | 已发布版本整数≥1；从未发布时为null，不发明版本0 |
| S-CONTENT.body / paragraphs / next_cursor | 纪要body为Markdown string；转写paragraphs为对象数组；不适用项为null；末页next_cursor=null |
| S-CONTENT.source | {provider:"TENCENT_MEETING", connection_ref:string, provider_record_file_id:string, profile_version:string}；不能由调用方写入 |
| S-OPERATION.execution_policy | HUMAN_CONFIRM / TRUSTED_MEMBER / APPROVED_SERVICE；冻结入库；智能体始终按HUMAN_CONFIRM执行 |
| S-JOB.kind | SOURCE_QUERY / MEETING_REFRESH / RECORDINGS_REFRESH / CONTENT_FETCH / CREATE / DELIVERY / SYNC；状态严格按第8章 |
| S-JOB.result | 未成功时null；成功时只能是对应kind的固定对象。SOURCE_QUERY含items/next_cursor/observed_at/source_scope/has_more；读取任务含resource_id/resource_version/state；CREATE含operation_id；DELIVERY含delivery_id；SYNC含accepted_count/skipped_count/next_cursor |
| S-EVENT.resource_type | meeting / recording / asset / operation / authorization；根据第9.2.6表固定，不接受任意资源类型 |
| S-SUBSCRIPTION.event_types | 第9.2.6枚举的非空去重数组，最多10项；contract_version必填且只能legacy/1.0或meeting.gateway/1.1；不能同一个订阅两种版本 |
| S-ERROR（错误时） | code为HTTP状态整数；error_code为固定数值目录项；reason/message_key/message/trace_id为string；data={retryable:bool,retry_after_seconds:int≥0或null,upstream_code:string或null} |
| 新版成功envelope | code=0，error_code=0，reason=null，message_key=null，message="success"，trace_id必填，contract_version="meeting.gateway/1.1"，data为业务响应；该规则不改legacy响应 |

稳定错误数字目录的RC1项不重新编号；RC2新增reason对应编号写入`contracts/internal/v1.1/error-codes.json`，唯一且发布后不可重用。普通接口调用方以reason作分支，不能解析message判断权限或重试。所有错误项的HTTP、retryable按第19章确定，未知新增项在合同检查时阻断发布。

### 9.2.6 内部事件枚举、发生条件与旧事件适配

归属：REQ-EVENT-002、REQ-MIGRATE-001；由A-EVENT-002-01/02、A-MIGRATE-001-01/02及A-LIVE-004验收。以下是网关事件，不是腾讯Webhook事件名。

| 新版event_type | resource_type | 产生条件 | legacy/1.0映射 |
|---|---|---|---|
| meeting.created | meeting | 网关创建得到确定的腾讯meeting_id并成功提交，或腾讯created通知经源查询确认目标存在；同资源创建版本只产生一次 | 网关创建对应meeting.create.succeeded；外部创建发现对应meeting.synced |
| meeting.updated | meeting | 已知元数据可观察字段发生变化，且不是下面ENDED转移；单纯刷新observed_at不产生事件 | meeting.synced |
| meeting.ended | meeting | 明确从非ENDED观察到ENDED；首次导入一个已结束的历史会议不回放其结束通知 | meeting.synced |
| recording.ready | recording | 文件详情确认录制可获取；并非仅收到转码完成事件 | meeting.synced；不得伪造asset.ready正文 |
| transcript.ready | asset | 完整转写版本进入READY，存储和事务提交成功 | meeting.asset.ready，asset_type=transcript |
| minutes.ready | asset | 固定纪要profile的完整版本进入READY | meeting.asset.ready，asset_type=minutes |
| meeting.operation.failed | operation | 本地拒绝/明确上游失败造成Operation进入FAILED；正常等待或UNKNOWN不产生该事件 | 无对应旧事件，不向旧订阅发送新事件名 |
| meeting.operation.unknown | operation | 创建已发送但没有可证明的最终结果，Operation进入OUTCOME_UNKNOWN | meeting.create.unknown |
| meeting.resource.invalidated | meeting/recording/asset | 已确认源资源删除，或已发送资源因访问撤销而需通知消费者停止使用 | 同名；payload保持旧合同 |
| meeting.authorization.revoked | authorization | 已知订阅主体对应授权被明确撤销，只通知该主体且不含原资源正文 | 同名；payload保持旧合同 |

旧`meeting.synced`不应一律改成新`meeting.created`：首次按需导入历史元数据并非真实创建。对无新版对应语义的旧刷新通知，新版不发事件。第13章业务键在新版规范事件层去重；每个订阅只序列化其登记版本一次。撤权控制事件允许发送给原获授权且客户端仍启用的同一接收方，其他资源通知按当前授权阻止；已禁用客户端不再投递任何消息。

映射为旧`meeting.synced`的recording.ready使用所属meeting_id作为legacy resource_id，附录制状态只限原合同允许字段，不能将recording_id冒充meeting_id。所有事件体均受大小32KiB上限约束，越界进入DEAD并报告EVENT_PAYLOAD_INVALID，不截断敏感数据后继续发。


## 9.3 API Contract 与入口清单

归属：REQ-API-001/002/003、REQ-AUTH-001、REQ-EVENT-002、REQ-DOC-001。`/api/v1`是网关前缀，不是腾讯上游路径。

| Operation ID | 对内入口 | 成功码 | 目标行为 / 兼容 |
|---|---|---:|---|
| AUTH-EXCHANGE | POST /api/v1/auth/exchange | 200 | 员工令牌兑换；沿用现有字段 |
| AUTH-TOKEN | POST /oauth/token | 200 | client_credentials/授权码/refresh，不自建员工账号 |
| AUTH-REVOKE | POST /oauth/revoke | 200 | 撤销指定票据，不暴露票据是否属于其他客户端 |
| MEETING-CREATE | POST /api/v1/meetings | 202 | 登记策略决定待确认或入队，幂等 |
| OP-READ | GET /api/v1/operations/{id} | 200 | 当前主体有权的操作结果 |
| OP-CONFIRM | POST /api/v1/operations/{id}/confirm | 200 | 新增内部系统员工确认入口；AGENT/SERVICE拒绝 |
| OP-REJECT | POST /api/v1/operations/{id}/reject | 200 | 只允许未发往腾讯的本地操作；不是取消真实腾讯会议 |
| SOURCE-QUERY | POST /api/v1/meeting-queries | 202 | 第一期按腾讯会议 ID 或当前员工时间窗查询；企业窗口拒绝；返回 job_id |
| CATALOG-LIST | GET /api/v1/meetings | 200 | 保留本地目录含覆盖范围，不宣称企业全量 |
| MEETING-READ | GET /api/v1/meetings/{id} | 200/202 | 缺缓存或过期默认 ensure 并返回 202；显式 cache 只读本地。元数据刷新不发事件 |
| RECORDING-LIST | GET /api/v1/meetings/{id}/recordings | 200/202 | 与 MEETING-READ 相同的 ensure 默认；不发元数据事件 |
| TRANSCRIPT-READ | GET /api/v1/recordings/{id}/transcript | 200/202 | 第一期走员工 OAuth；缺缓存默认 ensure；完整版本才发布 |
| MINUTES-READ | GET /api/v1/recordings/{id}/minutes | 200/202 | 第一期走员工 OAuth；固定腾讯原生纪要；缺缓存默认 ensure |
| TICKET-ISSUE | POST /api/v1/assets/{id}/download-tickets | 201 | purpose必填；对重复Idempotency-Key返回同ticket |
| DOWNLOAD | GET /api/v1/downloads/{ticket} | 200/206 | 同主体Bearer；单一Range；416拒绝多段/越界 |
| JOB-READ | GET /api/v1/jobs/{id} | 200 | 查询工作状态和已授权结果 |
| SYNC-REQUEST | POST /api/v1/sync-jobs | 202 | 保留补导高级入口，不是普通读取前置条件 |
| SUBSCRIPTION | POST/GET/PATCH /api/v1/subscriptions[/{id}] | 201/200 | 当前client自己的订阅；更新使用If-Match |
| DELIVERY-READ | GET /api/v1/subscriptions/{id}/deliveries | 200 | 当前client查看脱敏投递状态 |
| TENCENT-EVENT | GET/POST /callbacks/tencent/events/{receiver_id} | 200 | 腾讯专用响应体，不用业务envelope |
| TENCENT-OAUTH | GET /callbacks/tencent/oauth/{application_id} | 302 | 核对state后回跳登记内部地址，不返回Token到URL |
| MCP | POST /mcp | 协议码 | Streamable HTTP；既有7工具+源查询/作业状态2工具 |
| ADMIN | /api/v1/admin/... | 200/201 | 应用、连接、授权、诊断、setup；最小运维面 |

公开修改配置/订阅须If-Match。CREATE、SOURCE-QUERY、TICKET-ISSUE、SUBSCRIPTION创建须Idempotency-Key；ensure读取按“主体+连接+资源+类型+版本”去重，不能每次GET增加同一待处理作业。

## 9.4 创建策略判定表（DESIGN，待随本稿评审）

| 主体 | 客户端策略 | 前置授权 | 创建初始状态 |
|---|---|---|---|
| MEMBER | TRUSTED_MEMBER | 有效员工、连接、create.self或on_behalf范围 | QUEUED |
| MEMBER | HUMAN_CONFIRM | 相同授权 | AWAITING_CONFIRMATION |
| MEMBER | APPROVED_SERVICE | 不匹配 | 403 CLIENT_POLICY_MISMATCH |
| SERVICE | APPROVED_SERVICE | allow_service=true、meeting.create.service、显式主持人和连接范围 | QUEUED |
| SERVICE | 其他 | 不匹配 | 403 CLIENT_POLICY_MISMATCH |
| AGENT | 任意策略 | 当前员工和AgentGrant允许创建 | AWAITING_CONFIRMATION，智能体不可自确认 |

默认不要求所有新客户端直接创建；管理员为具体可信内部系统启用TRUSTED_MEMBER或APPROVED_SERVICE。这个显式授权一次完成后，业务调用不依赖Meeting Portal。旧客户端策略不被自动提升。第一期只实现 D-04、D-08 和 D-23：TRUSTED_MEMBER 且主持人是当前员工，以及 10 分钟到期的 HUMAN_CONFIRM。APPROVED_SERVICE 与 on_behalf 第一期拒绝。

## 9.5 上游映射与能力边界

归属：REQ-APP-001、REQ-API-002/003、REQ-CONTENT-001；EXT仅支持列出的API事实，网关字段和异步行为是DESIGN。

| 网关能力 | 上游API/路径 | 接入约束 |
|---|---|---|
| 创建一次性会议 | POST /v1/meetings | 主持人身份和企业策略以腾讯实际授权为准 [EXT-03] |
| 用户当前会议 | GET /v1/meetings | OAuth可见范围按其文档，不能称“用户所有会议” [EXT-10] |
| 用户已结束会议 | GET /v1/history/meetings/{userid} | 使用调用通道要求的身份，不从显示姓名猜映射 [CODE-C07] |
| 企业窗口会议 | GET /v1/corp/meetings，meeting_state=3/2/1 | 只企业自建；企业操作权限；映射UPCOMING/ONGOING/ENDED [EXT-01] |
| 按meeting_id查询 | GET /v1/meetings/{meeting_id} | 新增适配操作；调用者和连接权限双检 [EXT-11] |
| 会议录制 | GET /v1/records | 不以“有录制”作为“会议存在”的判断 [CODE-C07] |
| 企业录制 | GET /v1/corp/records | 不支持OAuth；按接口额度分页 [EXT-02] |
| 录制文件详情 | GET /v1/addresses/{record_file_id} | 文件与连接关联验证，敏感票据按契约处理 [CODE-C07] |
| 完整转写 | GET /v1/records/transcripts/details | 原生段落和more；新建自建应用STS前置条件 [EXT-04] |
| 腾讯原生纪要 | GET /v1/smart/minutes/{record_file_id} | RC2 llm=3/text_type=1，只有内容生成后交付 [EXT-08] |
| STS | POST /v1/app/sts-token + common.sts-token | 请求关联号与回调票据分开 [EXT-05/06] |



## 9.6 继承Schema的冻结定义与新增管理字段

归属：REQ-APP-001、REQ-AUTH-001/002、REQ-DOC-001、REQ-MIGRATE-001。继承的基线为第1章ZIP中的`app/schemas/requests.py`，文件SHA-256为`8edcfb3ec2477d701c8839a577a9c239293e7f1c1e22de130dea50360c41f2a1`，不能跟随未固定的远端main自动变化。下表列出完整字段集合；同名字段未在第9.2节覆盖时保留该固定DTO的类型、长度和默认。部署编译合同的工具必须读取这份不可变基线，不允许实现者根据名称自行补字段。

| Schema/固定DTO | 基线required fields | 基线optional fields及default |
|---|---|---|
| S-APP / ApplicationCreate | name:string1–128；application_type:ENTERPRISE_AKSK/THIRD_PARTY_OAUTH；tencent_corp_id:string1–64；sdk_id:string1–64；data_scope:enterprise/user；webhook_token:string8–128；webhook_encoding_key:string43–44；reason:string3–500 | environment:test/production=test；secret_id:string≤256=null；secret_key:string≤512=null；oauth_secret:string≤512=null；allowed_open_corp_ids:string[]≤20=[] |
| S-CLIENT / ClientCreate | name:string1–128；allowed_scopes:string[]1–30；owner_member_id:string；reason:string3–500 | client_type:CONFIDENTIAL/PUBLIC_MCP=CONFIDENTIAL；redirect_uris:string[]≤10=[]；agent_id:string或null=null；allow_service:bool=false |
| S-GRANT / GrantCreate | subject_type:MEMBER/SERVICE；subject_id:string；actions:string[]1–30；scope_type为第9.2枚举；reason:string3–500 | resource_ids:string[]≤1000=[]；connection_ids:string[]≤100=[]（RC2新建改必填且空=无权限）；asset_types为transcript/minutes/video/audio子集=[]；target_member_ids:string[]≤300=[]；purpose:ACCESS/INGESTION/MANAGE=ACCESS；effect:ALLOW/DENY=ALLOW；expires_at:AwareDatetime或null=null |
| S-AGENT-GRANT / AgentGrantCreate | client_id:string；agent_id:string1–128；actions:string[]1–10；reason:string3–500 | scope_type:SELF_CREATED/EXPLICIT/ORG_APPROVED=EXPLICIT；resource_ids:string[]≤1000=[]；connection_ids:string[]≤100=[]（RC2新建改必填）；asset_types:string[]=[transcript,minutes]；target_member_ids:string[]=[]；expires_at:AwareDatetime或null=null |
| S-IDENTITY / IdentityBind | application_id:string；member_id:string；external_id:string1–128；external_corp_id:string1–128；verification_source:string3–500；reason:string3–500 | 无；未验证映射不得赋予VERIFIED |
| S-ENTERPRISE-CONNECTION / EnterpriseConnectionCreate | application_id:string；admin_member_id:string；admin_userid:string1–128；reason:string3–500 | 无；该操作者仅用于批准的企业级接口，不作为全部员工的默认主持人 |

上述基线所有DTO均禁止additionalProperties。AK/SK要求secret_id+secret_key且data_scope=enterprise，oauth_secret必须为空；OAuth要求oauth_secret且data_scope=user，secret_id/secret_key必须为空。allowed_open_corp_ids为空时OAuth仅接受应用配置中的企业，不能解释成所有企业均允许。新绑定不因同名员工自动匹配。

新管理更新对象仅允许目标创建DTO字段的显式子集，以及第9.2定义的启停、create_policy、contract_version等扩展；不允许更新id/org_id/created_by、历史request_hash、任何执行state或审计字段。任何更新需If-Match当前version和reason，应用类型/租户/已有连接的外部身份不可原地改写；改变这些字段需创建新配置并显式迁移消费者绑定。

S-SUBSCRIPTION更新允许destination_ref、event_types、connection_ids、resource_ids、enabled，不能更改client_id或历史已投递事件版本。旧合同转换必须新建订阅并禁用旧订阅，避免待投递消息在中途换结构。


# 10. Requirement Unit

本章的24个需求是实施范围；N1/N2由对应正向Acceptance覆盖，N3由对应负向Acceptance覆盖。正向Acceptance亦检验其关键失败恢复结果；第21—23章列出参数化输入和注入点。代码路径是RC1可复用/拟变更定位，不是已经完成的实施计划。


## REQ-ARCH-001 — 独立服务与接口优先边界

### Goal
复用RC1而不是新建员工会议平台。

### Normative Requirement

- **REQ-ARCH-001.N1**：MUST 保持Meeting独立服务、数据库和迁移，Backend仅提供身份，REST/MCP复用同一业务服务。 → `A-ARCH-001-01`。

- **REQ-ARCH-001.N2**：MUST 使可信内部系统在不访问Meeting Portal业务页面的情况下完成认证、创建、查询、内容获取和状态消费。 → `A-ARCH-001-01`。

- **REQ-ARCH-001.N3**：MUST NOT 新增第4.2节的业务平台能力，MUST NOT 直接读写Backend/Task/Knowledge业务表。 → `A-ARCH-001-02`。

### Inputs
RC1源码、已配置Backend身份端点、接口消费者。

### Preconditions
PRE-ARCH-001-01：基础配置有效；已安装身份增量接口。

### Authoritative State
SOT=本PRD边界；Observed=服务入口；Derived=服务依赖图。

### State Transition
独立服务未启动→初始化自身连接池→READY；不引入共享业务进程。

### Allowed Side Effects
ALLOW：Meeting代码/数据库；Backend身份模块和有归属的router注册段；最小运维路由。

### Forbidden Side Effects
DENY：兄弟服务业务数据、员工登录体系、OA流程、录制引擎。

### Ownership Scope
FILE/SECTION：第12章管理清单；RESOURCE：本服务。

### Idempotency
首次启动建立连接；再次启动不生成员工或重复注册业务流程。

### Failure Semantics
F-ARCH-001-01：身份服务不可用→503 IDENTITY_SERVICE_UNAVAILABLE；进程live可真、业务ready为假；无业务源写入；可在恢复后重试。

### Postconditions
POST-ARCH-001-01：内部测试消费者完成业务调用，无Portal业务HTTP请求。

### Invariants
INV-ARCH-001-01：业务接口不依赖Portal确认页面；相同领域操作只有一个Owner。

### Error Codes
`IDENTITY_SERVICE_UNAVAILABLE`；HTTP映射与retry定义见第19章。

### Acceptance
`A-ARCH-001-01`；`A-ARCH-001-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_arch_001.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/main.py、app/runtime.py、app/api/、integration/backend/、scripts/integrate.py。


## REQ-APP-001 — 双通道应用配置与确定性连接选择

### Goal
集中托管腾讯配置，不让内部系统分别管理腾讯鉴权。

### Normative Requirement

- **REQ-APP-001.N1**：MUST 支持ENTERPRISE_AKSK和THIRD_PARTY_OAUTH配置，应用、连接、内部client分别存储，并只通过已授权connection_ref选连接。 → `A-APP-001-01`。

- **REQ-APP-001.N2**：MUST 分别记录配置有效、Webhook验证、票据可用和真实能力探测结果；setup输出网关生成的回调标识。 → `A-APP-001-01`。

- **REQ-APP-001.N3**：MUST NOT 把AK/SK与OAuth密钥互换，MUST NOT 在某连接失败后自动换连接、换操作者或提升权限。 → `A-APP-001-02`。

### Inputs
S-APP、S-CLIENT、connection_ref、If-Match和管理员reason。

### Preconditions
PRE-APP-001-01：管理员有application.manage；密钥存在；组织绑定明确。

### Authoritative State
SOT=应用/连接配置；Observed=腾讯探测；Derived=单次调用能力。

### State Transition
DISABLED→显式启用；连接探测状态独立变化。

### Allowed Side Effects
ALLOW：当前组织应用/连接行、加密凭据版本、脱敏探测记录。

### Forbidden Side Effects
DENY：别的组织配置、腾讯控制台未知管理API、未选连接。

### Ownership Scope
ROW/FIELD：当前组织Application、Connection、Credential。

### Idempotency
同If-Match和同内容重复配置不增加密钥版本；不同已应用版本返回冲突。

### Failure Semantics
F-APP-001-01：不支持通道→409 UPSTREAM_CAPABILITY_UNAVAILABLE；0腾讯调用；保留配置；非重试错误。

### Postconditions
POST-APP-001-01：调用轨迹唯一标明application/connection/鉴权类别，但不含密钥。

### Invariants
INV-APP-001-01：来源连接固定；配置保存成功不等于业务探测成功。

### Error Codes
`UPSTREAM_CAPABILITY_UNAVAILABLE`；HTTP映射与retry定义见第19章。

### Acceptance
`A-APP-001-01`；`A-APP-001-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_app_001.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/schemas/requests.py、app/services/admin_service.py、app/services/connection_service.py、app/integrations/tencent_meeting/client.py。


## REQ-AUTH-001 — 内部应用认证与三类主体

### Goal
内部调用方只持有Meeting凭据，并能代表经过验证的员工。

### Normative Requirement

- **REQ-AUTH-001.N1**：MUST 保留员工exchange和系统client_credentials；每次解析token受众、client状态、到期和当前Backend成员/组织状态。 → `A-AUTH-001-01`。

- **REQ-AUTH-001.N2**：MUST 区分MEMBER/SERVICE/AGENT，发放的scope不得超过client及主体范围；执行、下载、投递均重验身份。 → `A-AUTH-001-01`。

- **REQ-AUTH-001.N3**：MUST NOT 信任请求体employee_id或approved标志作为身份，MUST NOT 共享Backend JWT签名密钥或将腾讯Token发给消费者。 → `A-AUTH-001-02`。

### Inputs
S-EXCHANGE或OAuth表单、Bearer、resource。

### Preconditions
PRE-AUTH-001-01：客户端已登记；Backend可核验其成员；service调用已显式开启。

### Authoritative State
SOT=Backend身份和Client/Token记录；Derived=Principal。

### State Transition
凭据验证→发票据→到期/撤销；刷新轮换单次消费，重用撤销该family。

### Allowed Side Effects
ALLOW：Token哈希、RefreshFamily、审计、Backend只读HTTP。

### Forbidden Side Effects
DENY：员工账号、组织主数据、外部腾讯业务。

### Ownership Scope
ROW：Client/Token；NONE：Backend账号写入。

### Idempotency
兑换可产生不同有效票据；revoke重复返回200且不暴露别人的票据。

### Failure Semantics
F-AUTH-001-01：身份服务失败→503 IDENTITY_SERVICE_UNAVAILABLE，0新票据；错误受众→401 AUDIENCE_MISMATCH，非重试；刷新重用→REFRESH_REUSE并撤销family。

### Postconditions
POST-AUTH-001-01：服务端Principal与认证绑定一致，原内部登录继续使用。

### Invariants
INV-AUTH-001-01：SERVICE没有伪造member_id；TOKEN权限不能超过实时ACL。

### Error Codes
`AUDIENCE_MISMATCH`, `IDENTITY_SERVICE_UNAVAILABLE`；HTTP映射与retry定义见第19章。

### Acceptance
`A-AUTH-001-01`；`A-AUTH-001-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_auth_001.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/services/auth_service.py、app/authorization/router.py、app/api/deps.py、integration/backend/app/api/meeting_identity.py。


## REQ-AUTH-002 — 员工映射与操作/资源权限

### Goal
把会议查看、正文、下载、创建分开，不以管理员采集替代员工授权。

### Normative Requirement

- **REQ-AUTH-002.N1**：MUST 使用(org_id,member_id)映射腾讯身份，权限为client范围、主体Grant、资源ACL、来源授权和AgentGrant交集，DENY优先。 → `A-AUTH-002-01`。

- **REQ-AUTH-002.N2**：MUST 对目录、源查询结果、详情、正文、下载、job结果和事件投递执行同一PermissionService；查询发现权独立于正文权。 → `A-AUTH-002-01`。

- **REQ-AUTH-002.N3**：MUST NOT 因为参加过会议、管理应用、知道腾讯ID或已缓存内容而授予正文/下载权；MUST NOT 跨组织返回资源存在性。 → `A-AUTH-002-02`。

### Inputs
S-GRANT、IdentityBinding、Principal、资源和动作。

### Preconditions
PRE-AUTH-002-01：映射由管理员证据或OAuth身份核实；新授予动作已登记。

### Authoritative State
SOT=Grant/ACL/Binding/Backend；Observed=资源来源；Derived=当前允许结果。

### State Transition
授权创建/撤销→组织policy_version递增→所有后续决定使用新版本。

### Allowed Side Effects
ALLOW：授权行、policy_version、脱敏ALLOW/DENY审计。

### Forbidden Side Effects
DENY：腾讯操作者提升、资源正文改写、其他组织数据。

### Ownership Scope
ROW：同组织策略；RESOURCE：授权作用域。

### Idempotency
重复同授权请求不产生多条生效Grant；同资源重复判定不扩权。

### Failure Semantics
F-AUTH-002-01：映射缺失→409 IDENTITY_UNBOUND；前置拒绝→403 PERMISSION_DENIED且0上游请求；资源级拒绝统一404 RESOURCE_NOT_ACCESSIBLE。

### Postconditions
POST-AUTH-002-01：查看元数据者只能取得元数据；撤权后缓存命中同样拒绝。

### Invariants
INV-AUTH-002-01：同Principal+action+resource+policy_version判定一致；范围先过滤后分页。

### Error Codes
`IDENTITY_UNBOUND`, `RESOURCE_NOT_ACCESSIBLE`；HTTP映射与retry定义见第19章。

### Acceptance
`A-AUTH-002-01`；`A-AUTH-002-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_auth_002.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/services/permission_service.py、app/services/connection_service.py、app/core/types.py。


## REQ-AUTH-003 — 腾讯OAuth授权与临时故障恢复

### Goal
保留员工独立授权，短时网络故障不迫使所有员工重新授权。

### Normative Requirement

- **REQ-AUTH-003.N1**：MUST 校验单次state、已登记回跳、open_id及允许企业；每条员工连接独立保存和加密令牌，续期按返回expires。 → `A-AUTH-003-01`。

- **REQ-AUTH-003.N2**：MUST 持分布式锁刷新；短时网络/5xx进入DEGRADED并退避，明确刷新凭据无效进入REAUTH_REQUIRED；刷新原子替换。 → `A-AUTH-003-01`。

- **REQ-AUTH-003.N3**：MUST NOT 使用宽泛异常将全部失败标成用户撤销授权，MUST NOT 覆盖另一员工连接或将Token放回跳URL。 → `A-AUTH-003-02`。

### Inputs
OAuth开始请求、auth_code/state、token/user_info返回。

### Preconditions
PRE-AUTH-003-01：已登记腾讯OAuth应用和内部回跳；用户在可信内部系统完成登录。

### Authoritative State
SOT=Connection/TokenVersion；Observed=腾讯有效期和身份。

### State Transition
按第8章OAuth状态机；关联state消费一次。

### Allowed Side Effects
ALLOW：当前连接票据、授权事务、退避作业、审计。

### Forbidden Side Effects
DENY：其他连接票据、腾讯全局账号、用户密码。

### Ownership Scope
ROW：单连接和授权事务。

### Idempotency
回调重放不再兑换auth_code；重复刷新只一个进程发送，其他读取已更新版本。

### Failure Semantics
F-AUTH-003-01：网络超时→DEGRADED/UPSTREAM_UNAVAILABLE可重试；open_id变化→BLOCKED_CONTRACT/UPSTREAM_IDENTITY_MISMATCH不可自动恢复；state失效→400 STATE_INVALID。

### Postconditions
POST-AUTH-003-01：临时故障后的成功刷新恢复ACTIVE，未丢失旧refresh凭据。

### Invariants
INV-AUTH-003-01：一次连接只对应一个已确认员工身份；临时故障不是重新授权证据。

### Error Codes
`BLOCKED_CONTRACT`, `STATE_INVALID`；HTTP映射与retry定义见第19章。

### Acceptance
`A-AUTH-003-01`；`A-AUTH-003-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_auth_003.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/services/connection_service.py、app/callbacks/router.py、app/integrations/tencent_meeting/client.py。


## REQ-AUTH-004 — STS票据异步关联

### Goal
让敏感内容调用不要求内部应用理解STS回调机制。

### Normative Requirement

- **REQ-AUTH-004.N1**：MUST 持久化STS生成请求并关联req_id、application、operator及有效期，只有合法回调匹配才启用票据。 → `A-AUTH-004-01`。

- **REQ-AUTH-004.N2**：MUST 支持回调先于生成响应、到期和并发续期；生成请求响应不能把状态直接标READY。 → `A-AUTH-004-01`。

- **REQ-AUTH-004.N3**：MUST NOT 将Webhook Token当STS，MUST NOT 接受未知应用/操作者回调票据或将票据正文写普通日志。 → `A-AUTH-004-02`。

### Inputs
显式生成或读取需要票据；valid_hours默认6；common.sts-token。

### Preconditions
PRE-AUTH-004-01：Webhook已通过验证；企业自建连接可用；所需管理员身份已核实。

### Authoritative State
SOT=STSRequest/TokenVersion；Observed=回调有效期。

### State Transition
REQUESTING→WAITING_CALLBACK→READY；异常按第8章。

### Allowed Side Effects
ALLOW：请求记录、加密缓冲票据、活动票据指针、票据维护作业。

### Forbidden Side Effects
DENY：调用方凭据、其他应用票据、业务会议创建。

### Ownership Scope
ROW：同应用STS记录；FIELD：活动指针。

### Idempotency
同应用同时需要票据只一个活动生成请求；重复同req_id回调不覆盖更新票据。

### Failure Semantics
F-AUTH-004-01：缺票据→对应读取Job WAITING_CONTENT(reason=STS_PENDING)；300秒无关联→STS_CALLBACK_TIMEOUT；回调不匹配→STS_CORRELATION_MISMATCH不启用；可显式再生成。

### Postconditions
POST-AUTH-004-01：内容调用使用该应用当前未过期STS，响应不包含票据。

### Invariants
INV-AUTH-004-01：req_id不是STS；票据只在已关联后成为活动状态。

### Error Codes
`STS_CALLBACK_TIMEOUT`, `STS_PENDING`, `WAITING_CONTENT`；HTTP映射与retry定义见第19章。

### Acceptance
`A-AUTH-004-01`；`A-AUTH-004-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_auth_004.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/services/connection_service.py、app/services/event_service.py、app/models/applications.py。


## REQ-API-001 — 内部系统驱动的一次性会议创建

### Goal
消除固定Portal二次确认，同时保留有依据的写操作控制。

### Normative Requirement

- **REQ-API-001.N1**：MUST 按第9.4节创建策略表处理MEMBER/SERVICE/AGENT，POST返回202和Operation；可信内部系统可直接入队。 → `A-API-001-01`。

- **REQ-API-001.N2**：MUST 实现内部系统的confirm/reject接口，冻结request_hash和创建参数；保存business_ref、来源client和实际operator；执行前重验权限。 → `A-API-001-01`。

- **REQ-API-001.N3**：MUST NOT 把approved=true当授权，MUST NOT 让智能体自确认，MUST NOT 强制TRUSTED_MEMBER再访问Portal或静默改变云录制选项。 → `A-API-001-02`。

### Inputs
S-CREATE、Idempotency-Key、Principal；确认使用S-CONFIRM。

### Preconditions
PRE-API-001-01：功能开关开启；策略/角色匹配；主持人和邀请成员映射齐全；腾讯能力可用。

### Authoritative State
SOT=Client策略/Operation；Observed=腾讯创建结果；Derived=归一化wire request。

### State Transition
新请求按策略进入QUEUED或AWAITING_CONFIRMATION，随后第8章转移。

### Allowed Side Effects
ALLOW：操作日志、确认、CREATE Job、一次上游创建、会议映射、成功Outbox。

### Forbidden Side Effects
DENY：重复创建、真实会议取消、OA审批数据、Portal必经跳转。

### Ownership Scope
RECORD：一次Operation；RESOURCE：它创建的腾讯会议。

### Idempotency
首次受理产生1个Operation；同key同归一化请求返回原Operation；不同请求409 IDEMPOTENCY_CONFLICT。

### Failure Semantics
F-API-001-01：权限变更→REJECTED/AUTHORIZATION_CHANGED且未发腾讯；上游明确拒绝→FAILED；发送后结果不明→OUTCOME_UNKNOWN，处理见REQ-TXN-001。

### Postconditions
POST-API-001-01：成功Operation关联真实meeting_id；失败不会伪造会议号或入会URL。

### Invariants
INV-API-001-01：机器调用由已登记策略决定；一个幂等业务请求最多一次自动上游创建attempt。

### Error Codes
`OUTCOME_UNKNOWN`；HTTP映射与retry定义见第19章。

### Acceptance
`A-API-001-01`；`A-API-001-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_api_001.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/api/business.py、app/schemas/requests.py、app/services/operation_service.py、app/models/operations.py。


## REQ-API-002 — 无需预导入的腾讯源会议查询

### Goal
内部系统能发现尚未入库的会议，包括没有录制的会议。

### Normative Requirement

- **REQ-API-002.N1**：MUST 新增POST /meeting-queries。第一期实现 MEETING_ID 与 USER_WINDOW 的互斥语义、能力检查、权限过滤和可续页Job结果；USER_WINDOW 受 D-10 约束。CORP_WINDOW 第一期返回拒绝且 0 上游调用（D-05）。 → `A-API-002-01`。

- **REQ-API-002.N2**：MUST 将GET /meetings保留为CATALOG，SOURCE结果明确连接、时间、scope和覆盖范围；成功后只为可见资源建立映射。 → `A-API-002-01`。

- **REQ-API-002.N3**：MUST NOT 用录制列表替代会议列表，MUST NOT 自动扩大OAuth可见范围或把已接受查询当作查询成功。 → `A-API-002-02`。

### Inputs
S-QUERY、Idempotency-Key、Principal。

### Preconditions
PRE-API-002-01：具有meeting.query.source及选定连接发现范围；后台Worker可领取。

### Authoritative State
SOT=上游观察与QueryRun；Derived=授权后的返回页。

### State Transition
QUEUED→RUNNING→SUCCEEDED/等待/失败；查询结果保存在Job并按当前授权再次过滤。

### Allowed Side Effects
ALLOW：query job、checkpoint、可见会议元数据和来源；上游只读。

### Forbidden Side Effects
DENY：未授权资源正文/标题、全企业自动采集、腾讯业务写入。

### Ownership Scope
ROW：QueryRun与授权会议；NONE：腾讯业务写。

### Idempotency
相同key与请求返回原Job；cursor只能沿原条件继续，新主体不能重放。

### Failure Semantics
F-API-002-01：错误通道→409 UPSTREAM_CAPABILITY_UNAVAILABLE且0上游；游标策略版本不同→409 AUTHORIZATION_CHANGED；扫描预算用尽保留cursor而不是虚假完整。

### Postconditions
POST-API-002-01：已知外部meeting_id即使本地不存在也可被有权者找到，无录制会议同样返回。

### Invariants
INV-API-002-01：source_scope准确；每个结果都通过资源权限；本地目录不冒充源查询。

### Error Codes
`AUTHORIZATION_CHANGED`；HTTP映射与retry定义见第19章。

### Acceptance
`A-API-002-01`；`A-API-002-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_api_002.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/api/business.py、app/schemas/requests.py、新增app/services/query_service.py、app/integrations/tencent_meeting/client.py。


## REQ-API-003 — 按需会议详情与录制元数据

### Goal
让普通内部调用不必先操作后台同步任务。

### Normative Requirement

- **REQ-API-003.N1**：MUST 以 ensure 为缺缓存或过期时的默认读取（D-16）。缓存新鲜返回 200；缺失或过期建立单一刷新作业并返回 202。显式 fetch=cache 只读本地。元数据刷新不产生对内事件（D-22）。 → `A-API-003-01`。

- **REQ-API-003.N2**：MUST 正确区分meeting_id、recording_group_id和record_file_id，返回每个文件的状态、observed_at和可用资产类型。 → `A-API-003-01`。

- **REQ-API-003.N3**：MUST NOT 在元数据响应暴露正文、分享密码、腾讯签名地址；MUST NOT 将空录制列表标为会议不存在。 → `A-API-003-02`。

### Inputs
meeting/recording ID、fetch、max_age_seconds、Principal。

### Preconditions
PRE-API-003-01：资源权限已通过；ensure连接有对应能力。

### Authoritative State
SOT=腾讯观察；Observed=Meeting/Recording缓存；Derived=新鲜度。

### State Transition
缓存新鲜→200；缺失/过期ensure→202同Job；刷新完成原子更新观察。

### Allowed Side Effects
ALLOW：已授权资源元数据、去重读取Job、审计。

### Forbidden Side Effects
DENY：未授权缓存、腾讯会议写入、重复Job风暴。

### Ownership Scope
ROW：同会议元数据、录制和读取Job。

### Idempotency
相同主体+资源+fetch类型同一活动Job；重复cache读取仅新增审计。

### Failure Semantics
F-API-003-01：上游暂时错误→Job重试且保留旧观察；权限撤销→404 RESOURCE_NOT_ACCESSIBLE；源确实删除→SOURCE_REMOVED，不能回退泄露旧资料。

### Postconditions
POST-API-003-01：内部应用可以查询state并继续获取内容，不需要手工导入页面。

### Invariants
INV-API-003-01：会议存在和录制存在是两件事；metadata/read不包含content/download。

### Error Codes
`RESOURCE_NOT_ACCESSIBLE`, `SOURCE_REMOVED`；HTTP映射与retry定义见第19章。

### Acceptance
`A-API-003-01`；`A-API-003-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_api_003.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/services/meeting_service.py、app/services/sync_service.py、app/integrations/tencent_meeting/mapper.py。


## REQ-CONTENT-001 — 完整转写和腾讯原生纪要交付

### Goal
内部系统获取腾讯已经生成的结果，不接收未标识的半份或替代内容。

### Normative Requirement

- **REQ-CONTENT-001.N1**：MUST 将转写分页保存checkpoint并去重pid；只有more=false且完整性检查通过才发布READY版本。 → `A-CONTENT-001-01`。

- **REQ-CONTENT-001.N2**：MUST 按S-CONTENT固定类型交付腾讯纪要，区分生成中、未开启、明确空内容、权限错误与失败；ensure可启动读取。 → `A-CONTENT-001-01`。

- **REQ-CONTENT-001.N3**：MUST NOT 将部分转写当完整内容，MUST NOT 用本地LLM或其他纪要模型补齐并标腾讯原生，MUST NOT 仅因todo空就判纪要失败。 → `A-CONTENT-001-02`。

### Inputs
recording_id、asset_type、fetch、分页limit/cursor；腾讯返回。

### Preconditions
PRE-CONTENT-001-01：正文权限；资源来源有效。第一期只使用该员工 OAuth 连接（D-12）。企业 STS 不作为第一期前置；后续企业通道在需要 STS 时，票据必须已经关联且未过期。

### Authoritative State
SOT=腾讯返回和已发布Asset版本；Derived=完整性/分页游标。

### State Transition
ABSENT/FETCHING/WAITING_CONTENT→READY或EMPTY；失败保留staging，不更新当前版本指针。

### Allowed Side Effects
ALLOW：暂存片段、私有内容对象、Asset版本、job checkpoint和ready Outbox。

### Forbidden Side Effects
DENY：已发布正文原地覆盖、无授权输出、摘要再生成。

### Ownership Scope
OBJECT/ROW：当前来源的内容版本与片段。

### Idempotency
同pid同bytes可复用；同pid不同bytes视为变更冲突并重新受控获取；同版本重复读取不重复发ready。

### Failure Semantics
F-CONTENT-001-01：页中断→RETRY_WAIT，从checkpoint继续；重复cursor无进展→UPSTREAM_PAGINATION_STALLED；完整性失败→UPSTREAM_CONTENT_INCOMPLETE；无源授权→BLOCKED不交付旧版。

### Postconditions
POST-CONTENT-001-01：发布版本具备完整标识与digest；读取分页引用同一个不可变版本。

### Invariants
INV-CONTENT-001-01：READY等于已取到并校验，不等于只收到腾讯成功事件。

### Error Codes
`RETRY_WAIT`, `UPSTREAM_CONTENT_INCOMPLETE`, `UPSTREAM_PAGINATION_STALLED`；HTTP映射与retry定义见第19章。

### Acceptance
`A-CONTENT-001-01`；`A-CONTENT-001-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_content_001.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/services/content_service.py、app/services/job_service.py、app/models/resources.py。


## REQ-DOWNLOAD-001 — 授权文件下载接口

### Goal
内部系统取得可控文件而不是可任意转发的腾讯原始链接。

### Normative Requirement

- **REQ-DOWNLOAD-001.N1**：MUST 将下载许可绑定主体、client、组织、asset版本、用途和有效期，首次开始60秒、会话3600秒；实际下载及续传重新鉴权。 → `A-DOWNLOAD-001-01`。

- **REQ-DOWNLOAD-001.N2**：MUST 只代理来源确认且allow_download允许的文件，支持单Range、容量并发限制和字节计量；每5秒或1MiB边界先到者复核权限。 → `A-DOWNLOAD-001-01`。

- **REQ-DOWNLOAD-001.N3**：MUST NOT 对内返回腾讯原始签名地址，MUST NOT 允许把ticket移交其他主体、任意URL代理或把已发送字节回收作为撤权承诺。 → `A-DOWNLOAD-001-02`。

### Inputs
asset_id、purpose、Idempotency-Key；Bearer/ticket及可选单Range。

### Preconditions
PRE-DOWNLOAD-001-01：具备下载动作和资产类型权限；媒体域名已登记；feature启用。

### Authoritative State
SOT=Asset+Ticket/Session+Grant；Observed=腾讯文件可下载状态。

### State Transition
ISSUED→ACTIVE→COMPLETED/EXPIRED/REVOKED；源版本变化则停止当前新取流。

### Allowed Side Effects
ALLOW：Ticket/Session、额度、流量审计；网络读取文件；临时缓冲但不永久全量缓存媒体。

### Forbidden Side Effects
DENY：源文件更改、未批准网络、他人票据读取。

### Ownership Scope
RESOURCE：特定asset版本；ROW：下载会话和quota。

### Idempotency
同key同asset返回同未过期ticket；过期key重放返回原过期结果，重新申请用新key。

### Failure Semantics
F-DOWNLOAD-001-01：权限撤销→403/DOWNLOAD_REVOKED；无效Range→416 RANGE_INVALID；源版本变化→409 SOURCE_VERSION_CHANGED；流中失败记录已发送字节，不伪造完整成功。

### Postconditions
POST-DOWNLOAD-001-01：接收方能校验实际字节/范围；授权撤销后新取流立即拒绝。

### Invariants
INV-DOWNLOAD-001-01：ticket不是独立的无限Bearer能力；分片不能拼接不同文件版本。

### Error Codes
`DOWNLOAD_REVOKED`, `RANGE_INVALID`, `SOURCE_VERSION_CHANGED`；HTTP映射与retry定义见第19章。

### Acceptance
`A-DOWNLOAD-001-01`；`A-DOWNLOAD-001-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_download_001.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/services/download_service.py、app/storage/safe_http.py、app/api/business.py。


## REQ-EVENT-001 — 腾讯回调接收与目标资源同步

### Goal
腾讯事件触发指定会议结果更新，不依赖员工Portal和短窗口全局扫描。

### Normative Requirement

- **REQ-EVENT-001.N1**：MUST 验签解密、限定载荷、关联应用并持久化Inbox后才返回腾讯要求的确认；GET验证与POST处理按外部合同。 → `A-EVENT-001-01`。

- **REQ-EVENT-001.N2**：MUST 按事件中meeting_id/record_file_id和已批准采集范围定向安排Job，处理成功/失败/删除与乱序，不受最近两天扫描限制。 → `A-EVENT-001-01`。

- **REQ-EVENT-001.N3**：MUST NOT 仅因事件到达就发布READY，MUST NOT 由事件创建员工授权或依赖PORTAL客户端才能调度个人连接。 → `A-EVENT-001-02`。

### Inputs
receiver_id、腾讯header、加密payload。

### Preconditions
PRE-EVENT-001-01：接收应用有效；Webhook配置在网关；回调路由公开但非内部管理API。

### Authoritative State
SOT=Inbox原始加密记录；Observed=事件提示；最终资源状态仍由确认读取得出。

### State Transition
RECEIVED→PROCESSING→PROCESSED/RETRY_WAIT/IGNORED；未知关联进入隔离记录不扩大范围。

### Allowed Side Effects
ALLOW：Inbox、定向读取Job、资源观察失效标志；只对已授权范围出站读取。

### Forbidden Side Effects
DENY：全组织自动开采、赋予ACL、把消息标题直接当最终资源事实。

### Ownership Scope
RECORD：单事件；RESOURCE：授权范围内的目标会议文件。

### Idempotency
同事件指纹只1个Inbox；各payload目标具有独立dedup key；重复POST可确认旧记录。

### Failure Semantics
F-EVENT-001-01：签名错误→401且0Inbox；DB失败→5xx不确认；未知事件→IGNORED并确认；失败纪要事件→明确FAILED观察不发布READY。

### Postconditions
POST-EVENT-001-01：内部系统后续可读到对应目标状态，旧会议晚到事件不会遗漏。

### Invariants
INV-EVENT-001-01：确认接收等于持久化，不等于业务处理完成。

### Error Codes
；HTTP映射与retry定义见第19章。

### Acceptance
`A-EVENT-001-01`；`A-EVENT-001-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_event_001.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/callbacks/router.py、app/services/event_service.py、app/services/connection_service.py。


## REQ-EVENT-002 — 对内部系统的签名事件交付

### Goal
内部系统不必持续高频轮询，也无需接入腾讯原始事件格式。

### Normative Requirement

- **REQ-EVENT-002.N1**：MUST 实现按client和连接/资源范围登记订阅、事务Outbox、签名投递、状态查询和重试；轮询是无回调接收者的替代入口。 → `A-EVENT-002-01`。

- **REQ-EVENT-002.N2**：MUST 发布第9章事件1.1合同并保留legacy订阅映射，投递前重新校验接收方身份/资源权限；同事件重试event_id不变。 → `A-EVENT-002-01`。

- **REQ-EVENT-002.N3**：MUST NOT 宣称跨网络exactly-once，MUST NOT 推送正文/密钥/签名文件URL或追随未登记重定向。 → `A-EVENT-002-02`。

### Inputs
S-SUBSCRIPTION、领域已提交事件、投递响应。

### Preconditions
PRE-EVENT-002-01：目的地址登记；订阅client有效；可使用通知签名密钥。

### Authoritative State
SOT=Subscription/Outbox/Delivery；Observed=接收方HTTP状态。

### State Transition
PENDING→SENDING→DELIVERED/RETRY_WAIT/SUPPRESSED/DEAD。

### Allowed Side Effects
ALLOW：Outbox/Delivery记录、受控HTTPS POST、审计。

### Forbidden Side Effects
DENY：订阅方数据库直接写入、未批准通知目的地。

### Ownership Scope
ROW：当前订阅和投递；NONE：消费方业务库直接写入。

### Idempotency
业务事件键相同只1事件；每个subscription至多1个活动delivery；响应丢失可重复POST且使用同event_id。

### Failure Semantics
F-EVENT-002-01：非2xx/网络错→按1、5、15、60、300、900、3600秒延后，最多8次实际投递后DEAD；撤权→SUPPRESSED；3xx不跟随。

### Postconditions
POST-EVENT-002-01：接收者可验签并用event_id去重；可查每次投递状态和下一时间。

### Invariants
INV-EVENT-002-01：没有业务提交就没有成功事件；接收方2xx不等于其下游OA处理完成。

### Error Codes
；HTTP映射与retry定义见第19章。

### Acceptance
`A-EVENT-002-01`；`A-EVENT-002-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_event_002.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/services/event_service.py、app/models/events.py、contracts/events/、examples/webhook_consumer.py。


## REQ-JOB-001 — 可续页作业、全局限流与错误语义

### Goal
修复读取链路的工程阻塞，不把限流等待当成业务失败。

### Normative Requirement

- **REQ-JOB-001.N1**：MUST 使用PostgreSQL租约与fencing提交checkpoint；按应用及单接口共享配额，WAITING_RATE/WAITING_CONTENT不增加error_attempt_count。 → `A-JOB-001-01`。

- **REQ-JOB-001.N2**：MUST 按第17/19章分类暂时错误、鉴权错误、日额度、内容生成及合同错误；分页从最后已提交位置继续。 → `A-JOB-001-01`。

- **REQ-JOB-001.N3**：MUST NOT 通过关闭限流完成验收，MUST NOT 因Worker重启从0重抓已提交所有页或由过期租约发布结果。 → `A-JOB-001-02`。

### Inputs
Job、checkpoint、quota bucket、腾讯响应或异常。

### Preconditions
PRE-JOB-001-01：数据库时钟用于额度；Worker身份有效；能力配置存在。

### Authoritative State
SOT=Job/Lease/Checkpoint/RateLimit；Derived=run_after。

### State Transition
第8章Job状态机；错误attempt上限8，读取临时错误延迟min(2**(n-1),300)秒；有效Retry-After取较晚。

### Allowed Side Effects
ALLOW：作业、额度、分片、审计；明确允许的只读上游请求。

### Forbidden Side Effects
DENY：重复CREATE网络发送、丢弃已提交checkpoint、跳过权限重验。

### Ownership Scope
ROW：Job与quota；OBJECT：暂存页。

### Idempotency
重复领取不产生两个有效lease；同页同digest合并，冲突页阻断。

### Failure Semantics
F-JOB-001-01：进程崩溃→lease到期后读任务续作；日额度→WAITING_RATE并最多每3600秒探测一次，不假设一分钟恢复；上游未知结构→FAILED UPSTREAM_CONTRACT_ERROR。

### Postconditions
POST-JOB-001-01：默认节流下多页转写与录制都能到终态，真实失败才消耗错误重试。

### Invariants
INV-JOB-001-01：全局配额不随副本倍增；等待不消耗失败预算。

### Error Codes
`UPSTREAM_CONTRACT_ERROR`；HTTP映射与retry定义见第19章。

### Acceptance
`A-JOB-001-01`；`A-JOB-001-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_job_001.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/services/job_service.py、app/services/rate_service.py、app/integrations/tencent_meeting/client.py、app/worker.py。


## REQ-MCP-001 — MCP复用会议接口与受限委托

### Goal
为智能体提供同一组能力，不依赖腾讯官方MCP或额外会议平台。

### Normative Requirement

- **REQ-MCP-001.N1**：MUST 保留既有7工具并新增meeting_query_source和meeting_job_status，使用2025-11-25 Streamable HTTP及当前REST领域服务。 → `A-MCP-001-01`。

- **REQ-MCP-001.N2**：MUST 验证MCP受众、client与AgentGrant，逐次tools/call重验；交互授权由登记的原内部系统consent入口承载。 → `A-MCP-001-01`。

- **REQ-MCP-001.N3**：MUST NOT 将tools/list可见当成执行授权，MUST NOT 提供Agent自批准工具或自动跨受众透传Token。 → `A-MCP-001-02`。

### Inputs
JSON-RPC请求、MCP token、工具严格参数。

### Preconditions
PRE-MCP-001-01：MCP开关开启；客户端登记；需要consent时指定consent_client_id/uri；REST领域已可用。

### Authoritative State
SOT=Auth/AgentGrant/Permission；Derived=本次工具列表与结果。

### State Transition
授权请求→员工批准→授权码→票据；工具调用进入相同Operation/Job状态。

### Allowed Side Effects
ALLOW：领域调用的同等副作用；MCP授权事务与审计。

### Forbidden Side Effects
DENY：腾讯官方MCP接入、独立ACL、模型持腾讯密钥。

### Ownership Scope
ENTRY：工具注册；ROW：委托；RESOURCE：共享会议服务。

### Idempotency
工具传入相同业务幂等key与REST共享同操作作用域；协议session不制造新业务操作。

### Failure Semantics
F-MCP-001-01：错误受众→401；无委托/撤销→PERMISSION_DENIED tool error；未配consent→AUTH_CONSENT_UNCONFIGURED，不重定向到虚构Portal。

### Postconditions
POST-MCP-001-01：智能体能查会议和结果，创建仅提出请求并由员工确认。

### Invariants
INV-MCP-001-01：相同主体资源动作在REST与MCP判定一致；工具描述不能授予权限。

### Error Codes
`AUTH_CONSENT_UNCONFIGURED`, `PERMISSION_DENIED`；HTTP映射与retry定义见第19章。

### Acceptance
`A-MCP-001-01`；`A-MCP-001-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_mcp_001.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/mcp/server.py、app/mcp/tools.py、app/services/auth_service.py、app/authorization/router.py。


## REQ-OPS-001 — 最小配置与接口诊断

### Goal
让运维配好连接即可供内部系统使用，不要求建设员工工作台。

### Normative Requirement

- **REQ-OPS-001.N1**：MUST 通过已有admin API/CLI提供应用、连接、员工映射、内部client、权限和订阅配置，以及回调setup导出。 → `A-OPS-001-01`。

- **REQ-OPS-001.N2**：MUST 把配置、身份、基础查询、Webhook、STS、内容探测分别显示，修复事件列表字段合同；官方调试工具是受控外部验证入口。 → `A-OPS-001-01`。

- **REQ-OPS-001.N3**：MUST NOT 将所有诊断合为一个成功标记，MUST NOT 让只读探测创建腾讯会议或使用未经证实的腾讯控制台修改API。 → `A-OPS-001-02`。

### Inputs
管理员凭据、固定probe枚举、connection_ref和已知资源样本。

### Preconditions
PRE-OPS-001-01：具备diagnostics.run；只读样本有权；可用上游网络。

### Authoritative State
SOT=应用配置；Observed=各探测结果；Evidence=脱敏诊断。

### State Transition
NOT_RUN→RUNNING→PASS/FAIL/BLOCKED，分别记每种probe时间。

### Allowed Side Effects
ALLOW：诊断记录、上游只读探测、配置维护审计。

### Forbidden Side Effects
DENY：真实创建/取消会议、正文写日志、强迫用户打开Portal。

### Ownership Scope
ROW：诊断；ENTRY：运维API/CLI。

### Idempotency
重复探测可更新独立观测，不修改应用策略；setup相同配置返回相同receiver路由。

### Failure Semantics
F-OPS-001-01：缺样本→BLOCKED DIAGNOSTIC_INPUT_MISSING；上游不可用→FAIL并保留实际错误，不改为凭据有效。

### Postconditions
POST-OPS-001-01：运维能定位哪一层未通过，内部应用无须知道腾讯签名细节。

### Invariants
INV-OPS-001-01：配置完成、鉴权成功和内容可读是不同状态。

### Error Codes
`DIAGNOSTIC_INPUT_MISSING`；HTTP映射与retry定义见第19章。

### Acceptance
`A-OPS-001-01`；`A-OPS-001-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_ops_001.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/services/diagnostic_service.py、app/api/admin/、app/cli.py、integration/portal/运维字段。


## REQ-DATA-001 — 最小持久化、来源与缓存保留

### Goal
存储服务于接口交付，而不是默认进行企业全量归档。

### Normative Requirement

- **REQ-DATA-001.N1**：MUST 保留第7章必要状态、同组织约束、来源连接和不可变内容版本；首次获取只采集明确请求或授权订阅的范围。 → `A-DATA-001-01`。

- **REQ-DATA-001.N2**：MUST 使用第13章哈希和第14章发布顺序；默认元数据180天、内容缓存30天、审计180天、诊断7天，部署管理员显式确认。 → `A-DATA-001-01`。

- **REQ-DATA-001.N3**：MUST NOT 将跨连接相同腾讯ID直接合并ACL，MUST NOT 通过缓存绕过当前来源授权或删改无ownership数据。 → `A-DATA-001-02`。

### Inputs
上游观察、授权来源、内容对象、保留策略。

### Preconditions
PRE-DATA-001-01：组织已确认保留策略；数据库和私有存储可用。

### Authoritative State
SOT=第7章状态表；Observed=带时间来源缓存。

### State Transition
暂存→验证→发布；到期先逻辑停用并阻止访问，再清除受管敏感正文；保留可审计墓碑。

### Allowed Side Effects
ALLOW：Meeting自有数据、加密对象、生命周期墓碑。

### Forbidden Side Effects
DENY：全企业默认抓取、永久缓存所有媒体、其他业务数据物理删除。

### Ownership Scope
ROW/OBJECT：来源和受管缓存；用户自有文件不归本服务。

### Idempotency
相同来源ID与相同内容digest不新建重复Asset；跨连接保留独立资源来源。

### Failure Semantics
F-DATA-001-01：文件落盘失败→DB不发布READY，保留旧版；digest不符→CONTENT_INTEGRITY_FAILED，隔离对象；未知ownership→PRESERVE并报告。

### Postconditions
POST-DATA-001-01：任何已交付结果都能追溯连接、授权和版本，不要求全量同步。

### Invariants
INV-DATA-001-01：缓存仅为观察；来源权和访问权分开。

### Error Codes
`CONTENT_INTEGRITY_FAILED`；HTTP映射与retry定义见第19章。

### Acceptance
`A-DATA-001-01`；`A-DATA-001-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_data_001.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/models/、app/storage/、app/services/content_service.py、app/services/maintenance_service.py。


## REQ-TXN-001 — 创建不确定结果与跨系统事务边界

### Goal
不把数据库回滚误当成腾讯远程创建已撤销。

### Normative Requirement

- **REQ-TXN-001.N1**：MUST 在腾讯创建前提交唯一attempt和冻结参数，网络结果确认后再原子提交会议映射、操作结果及Outbox。 → `A-TXN-001-01`。

- **REQ-TXN-001.N2**：MUST 对发送后超时、失联或结果提交失败记录OUTCOME_UNKNOWN或恢复记录；只允许核对链接到同参数会议或CLOSE_UNRESOLVED。 → `A-TXN-001-01`。

- **REQ-TXN-001.N3**：MUST NOT 自动再次发送不确定创建、自动取消腾讯会议当回滚，MUST NOT 在回滚失败时删除恢复备份。 → `A-TXN-001-02`。

### Inputs
QUEUED Operation、当前权限、腾讯响应或失败、受控核对请求。

### Preconditions
PRE-TXN-001-01：当前lease有效；幂等日志存在；已验证创建策略。

### Authoritative State
SOT=Operation/Attempt；Observed=腾讯真实结果；Evidence=核对记录。

### State Transition
QUEUED→EXECUTING→SUCCEEDED/FAILED/OUTCOME_UNKNOWN；不可证明未发出时一律UNKNOWN。

### Allowed Side Effects
ALLOW：预写attempt、腾讯一次创建、DB成功结果/outbox、恢复文件；人工核对只读腾讯。

### Forbidden Side Effects
DENY：第二次隐式POST、远程cancel、错误标FAILED代表没创建。

### Ownership Scope
RECORD：operation attempt；RESOURCE：外部创建结果；FILE：受管恢复备份。

### Idempotency
同attempt无重复自动网络执行；核对同一个已验证ID重复不生成新会议或事件。

### Failure Semantics
F-TXN-001-01：本地提交前失败→回滚到T0且0远程；远程成功后DB失败→保留attempt并标/恢复UNKNOWN；恢复回滚失败→ROLLBACK_FAILED，备份保留直到人工恢复验证并明确清理。

### Postconditions
POST-TXN-001-01：无法确认的操作对内部应用明确可见；绝不伪造创建失败证据。

### Invariants
INV-TXN-001-01：不存在跨腾讯与本地DB的虚构原子事务。

### Error Codes
`ROLLBACK_FAILED`；HTTP映射与retry定义见第19章。

### Acceptance
`A-TXN-001-01`；`A-TXN-001-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_txn_001.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/services/operation_service.py、app/services/job_service.py、app/models/operations.py。


## REQ-MIGRATE-001 — RC1兼容升级与受管安装

### Goal
将现有包演进为接口优先，不让升级静默扩大权限或覆盖主仓库。

### Normative Requirement

- **REQ-MIGRATE-001.N1**：MUST 实施第16章迁移：旧client保持HUMAN_CONFIRM，旧GET为cache，旧事件按legacy合同输出；新增范围默认空且需显式授予。 → `A-MIGRATE-001-01`。

- **REQ-MIGRATE-001.N2**：MUST 先生成迁移预览、T0备份和文件ownership清单，再应用schema与注册段；每个结果包含before/after digest。 → `A-MIGRATE-001-01`。

- **REQ-MIGRATE-001.N3**：MUST NOT 覆盖用户修改的受管片段、删除未知文件、自动把旧全范围配置变成新源查询权；不得通过requirement升级删除原源码。 → `A-MIGRATE-001-02`。

### Inputs
RC1 schema/配置、源文件、固定安装清单、迁移批准。

### Preconditions
PRE-MIGRATE-001-01：维护窗口暂停领取；连接/策略备份可读取；现有schema探测匹配。

### Authoritative State
SOT=当前配置；LastApplied=安装清单和Alembic版本。

### State Transition
DETECT→PREVIEW→BACKED_UP→APPLIED→VERIFIED；drift→BLOCKED。

### Allowed Side Effects
ALLOW：Meeting表的向前迁移、受管新文件和明确注册段、备份/清单。

### Forbidden Side Effects
DENY：任意主仓库文件、用户新增配置、腾讯业务源。

### Ownership Scope
FILE/SECTION/ROW：按第12章。

### Idempotency
二次apply无diff则0修改；drift不merge、不force。

### Failure Semantics
F-MIGRATE-001-01：未知版本→MIGRATION_SOURCE_UNSUPPORTED；文件drift→MANAGED_CONTENT_MODIFIED；应用失败→恢复本地受管范围T0；失败恢复→保留备份ROLLBACK_FAILED。

### Postconditions
POST-MIGRATE-001-01：旧接口消费者保持旧语义，新内部客户端经显式配置获得新增能力。

### Invariants
INV-MIGRATE-001-01：升级不提升权限；证据写明发生了哪些行/文件变化。

### Error Codes
`MANAGED_CONTENT_MODIFIED`, `MIGRATION_SOURCE_UNSUPPORTED`；HTTP映射与retry定义见第19章。

### Acceptance
`A-MIGRATE-001-01`；`A-MIGRATE-001-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_migrate_001.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：alembic/versions/新增迁移、scripts/integrate.py、contracts/legacy/、integration/。


## REQ-SEC-001 — 凭据、网络、文件与内容边界

### Goal
把网关的高权限接入收敛在明确安全边界内。

### Normative Requirement

- **REQ-SEC-001.N1**：MUST 对第18章威胁逐项实施控制与负向测试：密钥加密、受众、组织、路径、符号链接、SSRF、参数和返回脱敏。 → `A-SEC-001-01`。

- **REQ-SEC-001.N2**：MUST 使用固定腾讯API白名单、显式媒体及通知目的地址清单、连接池和有界请求；依赖必须带锁与来源digest。 → `A-SEC-001-01`。

- **REQ-SEC-001.N3**：MUST NOT 将密钥放日志/前端/模型上下文，MUST NOT 执行任意命令、跟随未批准跳转或接受来自正文的权限指令。 → `A-SEC-001-02`。

### Inputs
所有HTTP/工具/事件输入、密钥、存储路径和依赖包。

### Preconditions
PRE-SEC-001-01：已配置密钥环及服务凭据；部署网络清单存在。

### Authoritative State
SOT=登记策略/密钥环；Observed=请求与解析IP/文件属性。

### State Transition
校验通过才进入受管写入/网络；失败只写脱敏拒绝审计。

### Allowed Side Effects
ALLOW：准许的密钥密文、审计、网络读取和文件写入。

### Forbidden Side Effects
DENY：凭据泄露、路径逃逸、任意进程执行、私网扫描。

### Ownership Scope
FIELD：凭据；FILE：私有根；RESOURCE：网络allowlist。

### Idempotency
重复恶意输入重复拒绝，不累计扩权；密钥轮换保留历史解密kid直到受管重加密验证完成。

### Failure Semantics
F-SEC-001-01：违规→422 INVALID_REQUEST/403 NETWORK_TARGET_DENIED/403 PATH_OUTSIDE_ROOT；0受保护副作用；密文被篡改→CREDENTIAL_INTEGRITY_FAILED，拒绝调用。

### Postconditions
POST-SEC-001-01：内部系统只收到网关级凭据和授权结果，不收到腾讯敏感凭据。

### Invariants
INV-SEC-001-01：不可信内容永远不是授权或可执行指令。

### Error Codes
`CREDENTIAL_INTEGRITY_FAILED`, `INVALID_REQUEST`, `NETWORK_TARGET_DENIED`, `PATH_OUTSIDE_ROOT`；HTTP映射与retry定义见第19章。

### Acceptance
`A-SEC-001-01`；`A-SEC-001-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_sec_001.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/core/security.py、app/core/middleware.py、app/storage/、app/integrations/tencent_meeting/。


## REQ-OBS-001 — 面向接口接入的审计和排障

### Goal
让内部系统知道失败在哪一层，运维能定位而不读取所有会议正文。

### Normative Requirement

- **REQ-OBS-001.N1**：MUST 记录第19章阶段、trace_id、client、主体、资源、选定连接、结果、错误码和时长，并贯穿异步Job和Outbox。 → `A-OBS-001-01`。

- **REQ-OBS-001.N2**：MUST 保留error_code兼容映射并提供稳定reason、retryable和脱敏上游码；diagnostic结果和调用审计分开。 → `A-OBS-001-01`。

- **REQ-OBS-001.N3**：MUST NOT 将会议正文、完整请求/Authorization header或下载URL记入普通日志，MUST NOT 用HTTP200代替业务成功。 → `A-OBS-001-02`。

### Inputs
请求上下文、阶段结果、上游错误和执行计时。

### Preconditions
PRE-OBS-001-01：日志脱敏规则生效；业务写入有同事务审计能力。

### Authoritative State
SOT=不可回写授权的Audit/Trace；Evidence=只反映发生事实。

### State Transition
RECEIVED→AUTHENTICATED→AUTHORIZED→ROUTED→UPSTREAM/SCHEDULED→COMMITTED→DELIVERED；每阶段SUCCESS/FAIL。

### Allowed Side Effects
ALLOW：受管审计/trace/指标；不得从审计反向改变业务状态。

### Forbidden Side Effects
DENY：敏感正文、凭据、用户自有业务日志。

### Ownership Scope
ROW：Audit；FILE：受管结构化日志。

### Idempotency
重复请求同operation_id但不同request trace；审计记录每次实际尝试，业务幂等不删除审计。

### Failure Semantics
F-OBS-001-01：关键本地成功写无法落审计→同事务回滚；远程已发生结果不伪造回滚，使用恢复日志；遥测导出失败不重发业务请求。

### Postconditions
POST-OBS-001-01：内部系统能以trace_id定位动作，所有状态准确区分accepted/ready/succeeded。

### Invariants
INV-OBS-001-01：业务成功与HTTP受理不同；审计权限不隐式包含正文权限。

### Error Codes
；HTTP映射与retry定义见第19章。

### Acceptance
`A-OBS-001-01`；`A-OBS-001-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_obs_001.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：app/core/errors.py、app/services/audit_service.py、app/services/diagnostic_service.py、app/core/middleware.py。


## REQ-DOC-001 — 内部接入合同与可运行示例

### Goal
交付对象是内部接口开发者而非仅运维页面使用者。

### Normative Requirement

- **REQ-DOC-001.N1**：MUST 交付固定OpenAPI、全部新增严格Schema、MCP工具和事件合同、错误码表及员工/系统调用、轮询、回调验签、幂等示例。 → `A-DOC-001-01`。

- **REQ-DOC-001.N2**：MUST 示例按“获取网关凭据→源查询或创建→Job/Operation轮询→读取内容/下载→事件消费”运行，明确所有操作副作用。 → `A-DOC-001-01`。

- **REQ-DOC-001.N3**：MUST NOT 把未来文件写成当前已存在，MUST NOT 在示例内放真实密钥、依赖Portal业务步骤或使用Mock结果通过Golden验收。 → `A-DOC-001-02`。

### Inputs
已批准Schema、真实API导出、示例参数、绑定manifest。

### Preconditions
PRE-DOC-001-01：源码已实现对应contract；示例默认dry-run与只读，真实创建需显式开关。

### Authoritative State
SOT=固定contracts版本；Observed=由实现生成的OpenAPI；Evidence=合同diff/示例测试。

### State Transition
GENERATED→DIFFED→VALIDATED→PUBLISHED；差异需版本化确认。

### Allowed Side Effects
ALLOW：contracts/、examples/、docs/、测试Evidence；显式live测试可调用已批准腾讯样本。

### Forbidden Side Effects
DENY：自动公开秘密、未批准真实创建、覆盖内部应用工程。

### Ownership Scope
GENERATED_ONLY：合同；FILE：示例和文档。

### Idempotency
相同实现导出合同digest一致；示例重复创建用固定业务key不会二次POST。

### Failure Semantics
F-DOC-001-01：实现与合同不同→CONTRACT_DRIFT并阻止发布；缺参数→DEPLOYMENT_BINDING_MISSING退出非0，不造默认用户。

### Postconditions
POST-DOC-001-01：消费方只学习网关合同，不分别实现腾讯AK/SK/OAuth/STS。

### Invariants
INV-DOC-001-01：每个示例都可映射到明确API、权限、状态和错误。

### Error Codes
；HTTP映射与retry定义见第19章。

### Acceptance
`A-DOC-001-01`；`A-DOC-001-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_doc_001.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：contracts/、examples/、scripts/export_contracts.py、docs/内部系统接入说明。


## REQ-EVID-001 — 真实内部消费方与腾讯联调发布门禁

### Goal
以真正内部系统调用和真实腾讯结果证明交付，不只看测试数量。

### Normative Requirement

- **REQ-EVID-001.N1**：MUST 为每个Required AC输出第24章证据，包含目标commit、命令、exit、Oracle、资源摘要及digest；执行Synthetic和第26章Golden两组。 → `A-EVID-001-01`。

- **REQ-EVID-001.N2**：MUST 使任何第一期 Required 项 FAIL、SKIPPED 或 BLOCKED 导致 Release Gate 非 0。第一期真实测试覆盖员工 OAuth 连接上的源查询、TRUSTED_MEMBER 创建、OAuth 正文、下载、对内签名事件和 MCP。企业双通道、APPROVED_SERVICE 与企业 STS 不作为第一期 Required 现场项（D-05、D-07、D-08、D-12）。授权出口或消费方绑定缺失时，第一期现场项为 BLOCKED，不能写成 PASS（D-06、D-09）。 → `A-EVID-001-01`。

- **REQ-EVID-001.N3**：MUST NOT 把历史117项测试报告、SQLite、SDK结构校验或合成内部脚本替代真实消费方/真实PostgreSQL/真实MCP会话验收。 → `A-EVID-001-02`。

### Inputs
代码commit、绑定manifest、测试命令及输出。

### Preconditions
PRE-EVID-001-01：需实际环境的test已显式授权；真实非敏感会议样本就绪。

### Authoritative State
SOT=Evidence文件和实际执行记录；Derived=Release Gate。

### State Transition
未执行BLOCKED→实际执行PASS/FAIL/SKIPPED；Gate每次从证据重算。

### Allowed Side Effects
ALLOW：Evidence受管文件；按批准live scope发生测试副作用。

### Forbidden Side Effects
DENY：虚构PASS、真实敏感正文入共享证据、自动修改业务审批。

### Ownership Scope
GENERATED_ONLY：Evidence；RESOURCE：批准的测试范围。

### Idempotency
同一run证据不可覆写；新run新目录；Gate对同证据产生同结论。

### Failure Semantics
F-EVID-001-01：缺live绑定→BLOCKED；digest不符→EVIDENCE_INTEGRITY_FAILED；任一Required非PASS→RELEASE_GATE_FAILED/exit1。

### Postconditions
POST-EVID-001-01：RC2标识仅在所有Required证据通过后发布为联调通过；不扩写成生产批准。

### Invariants
INV-EVID-001-01：SKIPPED≠PASS，受理/实现/验证互不替代。

### Error Codes
`EVIDENCE_INTEGRITY_FAILED`, `RELEASE_GATE_FAILED`；HTTP映射与retry定义见第19章。

### Acceptance
`A-EVID-001-01`；`A-EVID-001-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_evid_001.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：tests/acceptance/、tests/live/、scripts/release_gate.py（目标新增）、reports/。


## REQ-GOV-001 — 需求语义、计划与评审门禁

### Goal
按附件模板建立Requirement→Code→Test→Evidence闭环。

### Normative Requirement

- **REQ-GOV-001.N1**：MUST 仅在PRD状态APPROVED_FOR_PLAN且本稿37章、24个需求完整、每个N项具备Acceptance时生成计划。 → `A-GOV-001-01`。

- **REQ-GOV-001.N2**：MUST 计划Todo按第29章字段记录REQ/AC、文件、状态、副作用、失败、验证和证据，review顺序按第30章。 → `A-GOV-001-01`。

- **REQ-GOV-001.N3**：MUST NOT 在REVIEW状态伪造审批或生成标verified的计划，MUST NOT 让Plan Agent补选未定义授权/事务语义。 → `A-GOV-001-02`。

### Inputs
PRD正文、状态、审批记录、traceability、计划输出。

### Preconditions
PRE-GOV-001-01：授权评审人已检查新增DESIGN决策。

### Authoritative State
SOT=已批准PRD及审阅记录；Evidence=静态语义检查报告。

### State Transition
REVIEW→APPROVED_FOR_PLAN由人工批准；IMPLEMENTED和VERIFIED分别需代码和Evidence。

### Allowed Side Effects
ALLOW：PRD审批元数据、计划文件、检查报告。

### Forbidden Side Effects
DENY：未经批准产品代码、修改需求以掩盖失败、伪造签名。

### Ownership Scope
FILE/SECTION：PRD、plan、review报告。

### Idempotency
相同PRD重复检查结果一致；已批准PRD内容改变即回到REVIEW。

### Failure Semantics
F-GOV-001-01：无审批→PRD_NOT_APPROVED；缺语义→SPEC_SEMANTIC_GAP；无AC/test/oracle→TRACEABILITY_GAP；均禁止计划生成。

### Postconditions
POST-GOV-001-01：计划只能实现已批准语义；未经运行的测试不标verified。

### Invariants
INV-GOV-001-01：模板完整性与功能验收是两个独立门禁。

### Error Codes
`PRD_NOT_APPROVED`, `SPEC_SEMANTIC_GAP`, `TRACEABILITY_GAP`；HTTP映射与retry定义见第19章。

### Acceptance
`A-GOV-001-01`；`A-GOV-001-02`。完整Given/When/Then/Oracle见第20章。

### Evidence
required test：`tests/acceptance/test_gov_001.py::test_positive` 与 `::test_negative`；required artifact：各Acceptance独立的 `evidence.json` 和脱敏 `assertions.json`；required digest：第13章的证据文件摘要与受管前后快照；required runtime output：实际pytest输出、exit code、Oracle实际值，不接受预填PASS。

**代码定位/候选修改范围**：docs/prd/、scripts/validate_prd.py（目标新增）、docs/实施计划与评审记录。


# 11. Side-Effect Contract

归属：REQ-ARCH-001、REQ-TXN-001、REQ-SEC-001、REQ-DOC-001。`DB Write`特指Meeting库；任何行均不允许直接写内部消费方业务库。`Business Source`特指腾讯会议业务对象。

| Operation | DB Write | File Write | Network | Cache | User Data | Business Source |
|---|---|---|---|---|---|---|
| PRD分析/合同diff/dry-run | NO | 仅显式--out证据路径 | NO | NO | NO | NO |
| 配置preview | NO | 仅显式报告 | NO | NO | NO | NO |
| 配置apply/迁移 | YES，仅受管配置/表 | YES，备份/受管段 | Backend身份只读 | 配置失效 | 仅批准配置 | NO |
| 员工exchange/系统token/revoke | YES，票据/审计 | NO | Backend身份只读 | 授权缓存 | 票据状态 | NO |
| OAuth回调/refresh/STS | YES，授权记录/票据 | NO | 腾讯授权端点 | YES，凭据密文 | 授权状态 | NO，不创建会议 |
| GET CATALOG/cache/operation/job | 审计YES，业务资源NO | NO | Backend身份只读 | NO | 读取授权内结果 | NO |
| POST SOURCE-QUERY | Job/checkpoint/授权元数据YES | 报告不含正文 | 腾讯只读 | YES | 受控元数据 | NO |
| GET ensure元数据/内容 | 审计/去重Job/读取结果YES | 内容临时对象YES | Backend+腾讯只读 | YES | 读取授权内容 | NO |
| POST创建TRUSTED/机器 | Operation/Job/审计YES | 恢复日志 | 腾讯创建1次 | 元数据 | 主持/邀请字段 | YES，仅一次性会议 |
| POST创建待确认 | Operation/审计YES | NO | Backend身份只读 | NO | 待确认参数 | NO |
| confirm | Operation/Job/审计YES | NO | 身份核验；实际创建由Worker | NO | 确认记录 | 后续Worker可创建 |
| reject/close unresolved | Operation/审计YES | NO | Backend身份只读 | NO | 本地请求状态 | NO，不能取消腾讯会议 |
| 腾讯Webhook | Inbox/Job/审计YES | NO | 由后续Job只读查询 | 失效/刷新 | 最小事件数据 | NO |
| 对内通知 | Outbox/Delivery/审计YES | NO | 登记地址HTTPS POST | NO | 只授权元数据 | NO |
| 下载许可/取流 | ticket/session/quota/审计YES | 受管临时缓冲 | 腾讯媒体只读 | 默认不落全媒体 | 已授权文件字节 | NO |
| 保留清理 | 墓碑/清理记录YES | 已到期受管正文删除 | NO | 清理 | 仅到期受管内容 | NO |
| MCP工具 | 与对应REST完全相同 | 同左 | 同左 | 同左 | 同左 | 同左 |
| live验收 | 批准测试范围 | 脱敏Evidence | 明确的腾讯/消费方 | 样本缓存 | 非敏感样本 | 仅显式批准创建 |

缓存、日志、telemetry、审计均属于副作用，不能将“腾讯只读”写成“系统零写入”。拒绝请求允许写脱敏安全审计；本文“0业务mutation”不包含该审计和必要的速率计数。要求0文件改动的preview默认stdout；使用--out时仅该文件为允许范围。

# 12. Ownership Contract

## 12.1 Ownership Type

归属：REQ-MIGRATE-001、REQ-DATA-001。使用FILE、SECTION、ENTRY、ROW、FIELD、GENERATED_ONLY、USER_OWNED；SHARED只用于说明主仓库文件中有受管段和用户段，不授予整文件所有权。

| 范围 | Ownership | 创建/更新者 | 不可触碰范围 |
|---|---|---|---|
| nodeskclaw-meeting/app、tests、docs、contracts | FILE/GENERATED_ONLY | Meeting开发/导出器 | 未登记用户自建文件 |
| Backend meeting_identity模块 | FILE | Meeting安装器记录的新增文件 | Backend其他认证实现 |
| Backend api/router.py注册项 | SECTION/ENTRY | 带marker及digest的安装器 | 注册段外所有字节 |
| 既有Portal运维扩展 | FILE/SECTION | 记录在安装清单的条目 | 员工业务工作台、原登录页面 |
| Meeting业务表 | ROW/FIELD | 各领域Owner | 其他org行、未知列来源的原始配置 |
| 私有内容对象 | OBJECT | Asset记录指定的storage_key | 用户上传的未知文件与symlink目标 |
| 调用方审批记录/业务页面 | USER_OWNED | 原内部系统 | Meeting无修改权 |
| 腾讯会议/录制 | WHOLE_RESOURCE的有限API操作许可 | 腾讯维护；网关只获明确创建/读取能力 | 无cancel/修改/权限外操作 |
| Evidence与恢复备份 | GENERATED_ONLY | 本run产生 | 旧run不可覆写，失败备份不可自动删 |

## 12.2 Ownership Rule

创建时记录managed_manifest：相对路径、owner、marker范围、last_applied_digest、base_version。更新只匹配自己的owner和digest；用户修改后保留内容并报告drift。升级只改变有明确ownership的ENTRY/SECTION/ROW。remove只禁用明确受管入口及本服务记录，不删除未知文件，不调用腾讯取消或删除接口。

## 12.3 Drift

`current_digest == last_applied_digest` 才允许受管更新。`!=`默认BLOCK，错误 `MANAGED_CONTENT_MODIFIED`；不提供无人确认的FORCE/MERGE。非受管段差异始终PRESERVE且以user_owned_digest证明未改。应用配置的腾讯观察与desired不一致只WARN并标drift，不擅改腾讯控制台。

# 13. Hash / Identity Contract

归属：REQ-DATA-001、REQ-API-001、REQ-MIGRATE-001、REQ-EVID-001。以下均为网关DESIGN，不代替腾讯自身签名算法。

## 13.1 Canonical JSON

对受管哈希输入使用 `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",",":"), allow_nan=False).encode("utf-8")` 对应的字节规则；字段名只用ASCII。拒绝重复JSON key、NaN、Infinity和浮点时间；编码UTF-8无BOM。对象key升序，数组顺序保留，只有明确无序的scope、invitee_member_ids、连接集合先去重校验再按Unicode code point排序。字符串不做隐含Unicode正规化；仅subject执行前文strip规则。

## 13.2 哈希与身份表

| 名称 | 精确算法/范围 | 包含与排除 |
|---|---|---|
| 文件digest | SHA256(file_bytes)，lowercase hex | 包括换行和BOM真实字节，不包含mtime/权限 |
| 受管文件树digest | 按POSIX相对路径UTF-8字节排序，拼 `path + NUL + hex_file_digest + LF` 再SHA256 | 路径大小写敏感；拒绝绝对路径/../symlink；不读.git、venv、secret、未知用户文件 |
| DB受管快照digest | 表名升序；每表行按主键字符串升序；每行canonical JSON后拼LF并SHA256 | 包括授权/配置/业务字段，排除单列在manifest标记的测量时间；审计表独立摘要，不混入业务0mutation比较 |
| 内容digest | SHA256(canonical({asset_type,profile,paragraphs或minute,todo,source_version})) | 含原始文本、段落顺序和模型/格式；不含抓取时间、storage_key、加密随机nonce |
| 外部资源键 | `(org_id, connection_id, provider_meeting_id)`；文件再带provider_record_file_id | 同源唯一；不同连接不自动合并ACL；meeting_code不作唯一键 |
| request_hash v2 | SHA256(canonical({hash_version:2,connection_id,normalized_request,wire,execution_policy})) | normalized含subject、UTC整秒、主持人、排序invitees、business_ref、录制设置；wire不含签名/nonce/token |
| 创建幂等作用域 | SHA256(canonical([org_id,client_id,actor_type,subject_id,agent_grant_id或null,"meeting.create"])) | REST/MCP audience不入业务幂等作用域，鉴权时仍验证audience；key另做SHA256 |
| 查询/许可幂等作用域 | 同上最后项替换明确Operation ID | Source Query条件与选连接都入request_hash；24小时内保留去重记录 |
| 腾讯事件去重键 | 优先SHA256(canonical([application_id,event_type,unique_sequence]))；无unique_sequence用trace_id；均无则SHA256(canonical([application_id,decoded_payload])) | 不使用加密随机字节作指纹；同事件标识不同payload_digest报EVENT_ID_CONFLICT隔离 |
| 内部事件业务键 | SHA256(canonical([org_id,connection_id,resource_id,event_type,resource_version,operation_id或null])) | 全量业务身份；重复抓同版本不产生新ready |
| Evidence manifest digest | SHA256(canonical([{path,sha256,size_bytes},...])) | 路径排序；不包含manifest自己的文件，防递归；含实际日志/断言/快照引用 |
| Token/secret verifier | SHA256(高熵token UTF-8)用于不透明Token比较；client_secret用带随机salt的scrypt(n=16384,r=8,p=1,dklen=32) | 原密钥不入普通DB日志；腾讯凭据需可解密所以用AES-256-GCM，不只存hash |

创建幂等记录至少保留至会议结束后180天；OUTCOME_UNKNOWN/CLOSED_UNRESOLVED至少保留180天且不自动允许同key新创建。旧request_hash v1按RC1算法保留，不重算旧Operation；新Operation用v2并记录hash_version。

## 13.3 游标与通知签名

新源查询cursor：Base64URL无padding编码canonical payload，再以专用密钥HMAC-SHA256签名；payload包含version、org/client/subject/agent、connection_ref、query_hash、policy_version、上游位置和下游位置、exp整秒；15分钟有效。只要绑定条件不同即拒绝，不从客户端cursor读取任意URL。

内部事件1.1签名输入严格为：

```text
ASCII(timestamp_seconds) + LF
+ ASCII(nonce) + LF
+ UTF8(event_id) + LF
+ lowercase_hex_SHA256(raw_HTTP_body)
```

`X-Meeting-Signature = v1=<lowercase_hex_HMAC_SHA256(subscription_secret, input)>`；同时发送 `X-Meeting-Timestamp`、`X-Meeting-Nonce`、`X-Meeting-Key-Id`。nonce为16随机字节Base64URL；接收端检查±300秒、constant-time签名、nonce在10分钟窗口未消费，并持久化event_id去重。重试保留event_id、更新timestamp/nonce和签名。消息体不重格式化后再验签。

腾讯AK/SK与Webhook签名使用其各自官方协议与RC1适配规则，不套用上述内部事件签名。[CODE-C07、EXT-07]

# 14. Transaction Contract

## 14.1 Transaction Boundary

归属：REQ-TXN-001、REQ-EVENT-001/002、REQ-JOB-001、REQ-MIGRATE-001。

| 事务 | TXN includes | TXN excludes |
|---|---|---|
| 本地创建受理 | 幂等索引、Operation、确认或CREATE Job、审计 | 腾讯网络请求、内部通知 |
| 创建attempt预提交 | 状态EXECUTING、唯一attempt、lease fence、冻结wire摘要 | 腾讯POST |
| 创建结果提交 | Meeting映射、Operation SUCCEEDED、outbox、审计 | 已发生的腾讯创建、对内HTTPS投递 |
| 回调接收 | Inbox、dedup、读取Job、审计 | 业务内容抓取、LLM、OA |
| 单页读取 | 当前页数据、checkpoint、lease校验 | 下页HTTP、整场内容发布 |
| 完整内容发布 | 不可变Asset索引、版本指针、READY事件 | 前序网络、文件暂存；媒体流不在DB事务里 |
| OAuth/STS激活 | 密文票据、关联记录、版本指针 | 外部授权响应或已收到回调 |
| 文件安装 | 受管文件/段与manifest原子替换 | 用户文件、Git push、腾讯资源 |

## 14.2 Commit Order

创建：校验身份/策略 → 幂等检查 → 本地受理提交 → Worker重验权限 → attempt预提交 → 腾讯POST一次 → 校验返回 → 本地结果+Outbox提交 → 内部系统轮询/通知。不能跨网络持有长时间DB事务。

内容：申请读取 → 逐页暂存+checkpoint → 校验末页和一致性 → 加密写同文件系统临时对象 → fsync → 原子rename → DB引用+READY+outbox提交。DB提交失败时对象是孤儿，不发布READY；按job引用保留24小时后清理明确受管孤儿。

安装：detect → preview → 验证ownership → T0备份 → stage → verify → 原子替换受管段 → 更新manifest → verify → evidence。

## 14.3 Failure Atomicity

T0是本地事务第一次mutation前的受管状态。**只对该本地事务范围**要求 `AfterRollback(managed_scope)==T0`；审计和恢复记录另列允许范围。

腾讯POST一旦可能发送，不能承诺腾讯恢复T0。此时保留attempt和不确定结果，不进行自动cancel或第二次create。Outbox投递也可能“接收者已收到但响应丢失”，只承诺at-least-once与event_id去重合同。

## 14.4 Rollback Failure

错误 `ROLLBACK_FAILED`，process exit非0；写入专用 `recovery/{run_id}/manifest.json`，包含范围、已成功步骤、失败步骤、T0文件digest、当前digest和恢复命令参数，不包含凭据明文。恢复备份设置hold=true，人工确认恢复与Oracle通过后，管理员显式清理；恢复失败期间不得按正常TTL删除。数据库恢复使用备份恢复到隔离实例先验证，再批准切换，禁止对活库猜测性逆向修改。

# 15. Conflict Contract

归属：REQ-API-001/002、REQ-JOB-001、REQ-MIGRATE-001、REQ-DATA-001。默认不存在last-writer-wins。

| Conflict | Detection | Default Behavior | Error | Mutation |
|---|---|---|---|---|
| 同幂等key不同参数 | request_hash不同 | BLOCK | IDEMPOTENCY_CONFLICT | 0业务变更 |
| 同资源不同组织 | org_id与Principal不一致 | DENY且隐藏存在性 | RESOURCE_NOT_ACCESSIBLE | 0资源变更 |
| 连接身份改变 | open_id/corp或mapping版本不匹配 | BLOCK | UPSTREAM_IDENTITY_MISMATCH | 只记录连接阻断 |
| 相同事件ID不同正文 | payload_digest不同 | QUARANTINE | EVENT_ID_CONFLICT | 不覆盖旧事件 |
| 同pid不同内容 | page/segment digest不同 | BLOCK本次快照 | CONTENT_VERSION_CONFLICT | 不发布READY |
| 旧lease提交 | lease_token或lease_until无效 | BLOCK | JOB_LEASE_LOST | 0checkpoint写 |
| 配置version不同 | If-Match不等 | BLOCK | CONFIG_VERSION_CONFLICT | 0配置写 |
| 受管段被用户修改 | current!=last_applied | BLOCK/PRESERVE | MANAGED_CONTENT_MODIFIED | 0原文件变更 |
| 同路径未知owner | manifest无归属 | PRESERVE/BLOCK | OWNERSHIP_UNKNOWN | 0删除/覆盖 |
| 游标策略或筛选改变 | cursor绑定不符 | BLOCK | AUTHORIZATION_CHANGED/CURSOR_INVALID | 0结果泄露 |
| 录制策略受企业锁定拒绝 | 上游明确拒绝 | BLOCK | UPSTREAM_POLICY_CONFLICT | 不尝试另一录制模式 |
| 删除事件与晚到ready | 删除/新观察时序与查询结果 | 先使来源健康失效，再读源核实 | SOURCE_REMOVED或WAITING_CONTENT | 不靠消息到达顺序恢复旧资源 |

# 16. Compatibility / Migration

## 16.1 Existing State

归属：REQ-MIGRATE-001。旧版本是ZIP固定的1.0.0rc1，初始Alembic revision `1d4f7c955b82`；旧目录为独立`nodeskclaw-meeting/`。本稿不是覆盖整个nodeskclaw仓库的新模板。

| 旧状态 | RC2迁移行为 |
|---|---|
| 所有创建prepare且不允许SERVICE | 旧client补create_policy=HUMAN_CONFIRM；新直接调用策略必须显式配置 |
| GET /meetings本地目录 | 保持，不偷偷变为上游全量查询 |
| 没有meeting.query.source/create.service | 不自动给旧token、grant、client新增scope |
| Grant空connection_ids表示宽范围的旧行为 | 迁移时展开为该旧授权当时可触及且同org的已启用连接集合；集合可能为空；未来新增连接不自动加入；预览列出变化 |
| 旧空数组且无法确定归属 | 不猜范围；保持旧原记录但标NEEDS_REVIEW，相关新增功能阻断，旧读取是否继续仅按旧合同与原权限执行，不扩权 |
| 旧Operation/request_hash | 保留hash_version=1、状态和参数；新v2不回写旧操作 |
| legacy订阅 | contract_version=1.0；继续旧事件名称/形状；新订阅必须显式1.1 |
| 旧Subscription.destination | 经原allowlist验证后登记destination_ref；失败不自动投递新地址 |
| Portal确认URL | 保留旧入口兼容；新增内部系统confirm接口为同一服务；普通新客户端不跳Portal |
| PUBLIC_BASE_URL/PORTAL_BASE_URL | 保留；生产仅无交互业务路径时Portal可不部署，校验不强制其服务可达；需要consent时必须登记内部consent_uri |
| 缺uv.lock | 在受控联网环境生成、审核并冻结；不能制造虚假的依赖锁 |

## 16.2 Migration

Detect固定版本与ownership → 输出scope/文件/schema差异 → 运维批准 → 暂停新写/领取 → 备份T0 → Alembic自动生成并评审迁移 → 补数据与legacy绑定 → 验证旧合同及负向授权 → 启动Worker → 运行Golden。

升级回滚只恢复受管本地代码/配置/schema备份；不能撤销升级期间已成功创建的腾讯会议。因此迁移窗口不执行live写测试，恢复后若存在新版本业务写，回退方案使用向前修复或恢复到隔离库核对，不盲目downgrade活库。

## 16.3 Unknown Ownership

无manifest、未知schema、新旧owner冲突一律PRESERVE并报告，禁止删除。若无法确定可访问范围，新增能力BLOCKED，具体原因随migration report输出；不能把“为了兼容”当作自动放大全量范围的理由。

# 17. External Dependency Contract

归属：REQ-APP-001、REQ-AUTH-003/004、REQ-JOB-001、REQ-DOC-001、REQ-EVID-001。

| name | repo / endpoint | version / immutable identity | required paths / APIs | fallback / offline / failure |
|---|---|---|---|---|
| nodeskclaw接口基线 | 用户指定GitHub仓库 | SHA 83edfb0d97f07920deb8bb9ce44a91e3e32cc3af；RC1 ZIP digest见第1章 | Backend身份addon、子项目布局 | 目标分支不同需diff和集成验收；不按main移动引用生成代码 |
| Backend身份 | 部署绑定backend_url | 实际运行commit写Evidence | 已交付meeting_identity模块的context/resolve | 不可用fail closed；不本地伪造员工 |
| Tencent REST | 固定api.meeting.qq.com | gateway upstream profile `tencent-meeting/2026-10-16` + 本章官方引用 | 第9.5节固定操作 | 无网络则SOURCE/create/ensure等待或失败；不回退个人MCP/管理员连接 |
| Tencent OAuth | 固定meeting.tencent.com OAuth端点 | 同profile，返回expires为时效依据 | authorize/access_token/refresh_token/user_info | 已过期token不继续使用；临时失败DEGRADED |
| Tencent Webhook | 配置后的网关receiver路由 | 验签/解密契约EXT-07 | GET challenge / POST事件 | 无匹配应用拒绝；失败不假确认 |
| PostgreSQL | 独立DATABASE_URL | RC2测试固定PostgreSQL 16大版本；实际patch及镜像digest在锁清单记录 | asyncpg、Alembic、行锁/lease | 不用SQLite替代多进程Gate；数据库不可用业务拒绝 |
| Python与包 | RC1 pyproject.toml | Python3.12；顶层基线沿用输入包；传递依赖以审核后的uv.lock固定 | FastAPI/SQLAlchemy/httpx/crypto等 | 构建缺锁BLOCKED；不静默升级到不受测版本 |
| MCP | modelcontextprotocol.io | 协议2025-11-25，SDK mcp>=1.23,<2并锁精确版本 | Streamable HTTP、授权发现与tools | 不宣称后续协议全兼容；SDK缺失不能标会话Gate通过 |
| 私有存储 | STORAGE_PATH | 受控本地/挂载文件系统根，部署路径绑定 | 临时文件、fsync、原子rename | 不支持同文件系统原子替换则部署检查失败 |
| 内部通知接收者 | 管理员登记destination_ref | 接收方commit、TLS配置、endpoint identity | HTTPS POST、签名校验和event_id去重 | 不可达按投递重试；轮询仍可查结果 |

部署包锁清单 `deploy/dependency-lock.json` 必含：服务Git commit、镜像repo@sha256、PostgreSQL镜像digest、uv.lock_sha256、Python/uv实际版本、MCP SDK版本。不得以未知hash的占位字符串通过校验；这些值由打包动作产生而非PRD编写者编造。

### 17.1 官方依据登记（EXT）

访问核对日期为2026-10-16；这些网页不保证永久不变，因此打包时冻结所依赖的字段映射与合同测试。企业实际开通结果以授权调用为准。以下URL以代码文本保存，便于文档离线追溯。

| ID | 官方文档 | 本稿使用的事实范围 |
|---|---|---|
| EXT-01 | `https://cloud.tencent.com/document/product/1095/52490` | 账户级会议列表/状态及AKSK限制 |
| EXT-02 | `https://cloud.tencent.com/document/product/1095/53224` | 企业录制列表、OAuth不支持、分页/范围 |
| EXT-03 | `https://cloud.tencent.com/document/api/1095/42417` | 创建会议与受企业设置约束的录制选项 |
| EXT-04 | `https://cloud.tencent.cn/document/product/1095/65111` | 转写段落、more、权限/STS前置条件 |
| EXT-05 | `https://cloud.tencent.com/document/product/1095/127650` | STS生成请求与有效期选择 |
| EXT-06 | `https://cloud.tencent.com/document/product/1095/127651` | STS事件关联 |
| EXT-07 | `https://cloud.tencent.com/document/api/1095/51608` | Webhook验签解密、GET3秒/POST5秒及确认字符串 |
| EXT-08 | `https://cloud.tencent.cn/document/product/1095/109458` | 腾讯智能纪要，不将todo空直接判失败 |
| EXT-09 | `https://cloud.tencent.com/document/api/1095/51257` | OAuth身份、令牌、scopes和服务器保管要求 |
| EXT-10 | `https://cloud.tencent.com/document/product/1095/42421` | 用户会议列表及OAuth创建来源范围 |
| EXT-11 | `https://cloud.tencent.com/document/product/1095/93432` | 通过会议ID查询、企业管理员和OAuth范围 |
| EXT-12 | `https://cloud.tencent.com/document/product/1095/121286` | smart.minutes事件目标文件与result=1/2 |
| EXT-13 | `https://cloud.tencent.com/document/product/1095/43704` | 腾讯错误分类依据 |
| EXT-14 | `https://modelcontextprotocol.io/specification/2025-11-25/basic/transports` | MCP Streamable HTTP |
| EXT-15 | `https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization` | 受众、授权发现、上下游令牌隔离 |

腾讯官方调试工具来源保留为RC1 `docs/PROVENANCE.md` 引用的 `https://cloud.tencent.com/document/product/1095/51815`；本轮该页抓取超时，不新增对其当前页面字段/权限的未经核实断言。网关的目标是可配合该工具测试，而不是自动修改其后台开关。

### 17.2 腾讯套餐与资源能力

商业版是用户提供的当前环境前提，不是“所有API和所有员工一定可用”的推论。应用种类、操作者身份、scope、云录制功能和内容生成状态仍分别校验。文档不承诺OAuth读取任意客户端来源的全部会议。遇到接口不支持所选授权通道，返回能力错误，不换连接。

源查询profile记录每个上游操作的路径、鉴权类型、必要参数、最大页大小、分页终止字段和实际能力探测时间。SDK/产品名称不作为权限证据；被腾讯拒绝的能力不能在网关中模拟成功。

# 18. Security Contract

归属：REQ-SEC-001，专项另关联对应Requirement；以下每行都有控制和负向Oracle。

| threat | control | acceptance / Oracle |
|---|---|---|
| path traversal | storage_key服务器生成；拒绝绝对路径、../和NUL；realpath保持根内 | A-SEC-001-02；outside_root_write_count=0 |
| symlink | 打开受管文件前lstat/禁止跟随；安装器拒绝符号链接目标 | A-SEC-001-02；symlink_target_changed=0 |
| arbitrary execution | API不接受shell、脚本路径或任意导入；记录内容只作为字符串 | A-SEC-001-02；spawn_from_input_count=0 |
| credential exposure | 腾讯可解密材料AES-256-GCM带kid/AAD；客户端secret哈希验证；响应/日志脱敏 | A-SEC-001-01/02；plaintext_secret_matches=0 |
| write containment | org_id来自认证，写入有org/ownership/版本条件 | A-AUTH-002-02、A-MIGRATE-001-02 |
| dependency provenance | Git固定SHA、锁文件digest、镜像digest、可复现构建输入 | A-DOC-001-02、A-EVID-001-02 |
| untrusted input | 严格DTO、请求≤1MiB、上游JSON≤16MiB、拒绝重复key与无效枚举 | A-SEC-001-02；oversize_success=0 |
| SSRF / DNS rebinding | 腾讯固定host；媒体/通知精确host；解析IP验证并固定本次连接目标；重定向不跟随 | A-DOWNLOAD-001-02、A-EVENT-002-02 |
| 内网通知地址 | 仅管理员显式批准host+CIDR可访问内部业务接收器；metadata/link-local/loopback始终禁用 | A-SEC-001-02；unapproved_private_access=0 |
| OAuth CSRF / code replay | state随机且一次性，绑定原client/member/redirect；PKCE用于下游公共MCP | A-AUTH-003-02、A-MCP-001-02 |
| data leakage | 权限先于正文/下载/投递；目录不返回总企业计数或非授权标题 | A-AUTH-002-02 |
| permission boundary | DENY优先、角色不等于资源权、员工停用下一请求生效 | A-AUTH-002-01/02 |
| 伪造审批与confused deputy | create_policy服务器登记；confirm需真实员工及归属；Agent无confirm工具 | A-API-001-02 |
| Webhook重放/篡改 | 签名校验+事件指纹；内部通知±300秒/nonce缓存/event_id去重 | A-EVENT-001-02、A-EVENT-002-02 |
| 提示注入 | 转写/纪要内容不参与路由、权限和执行；MCP输出标记为来源数据 | A-SEC-001-02、A-MCP-001-02 |

会话和授权撤销边界：本地成员/Grant/Client在每个请求及Worker执行时重新验证，不靠Token过期后才撤销。腾讯侧撤销只有在回调或下一次上游检查观察到后才能确知；敏感缓存读取要求来源健康观察不超过60秒，过期检查失败则拒绝正文，不承诺未知的外部撤销瞬间可知。

# 19. Observability

归属：REQ-OBS-001、REQ-JOB-001。阶段采用 `RECEIVE/AUTHENTICATE/AUTHORIZE/ROUTE/FETCH/SCHEDULE/PERSIST/PUBLISH/DELIVER/RECOVER`。每条阶段记录含operation或job id、trace_id、stage、status、UTC timestamp、org/client/actor、资源身份、连接、result、error reason、duration_ms；没有operation时使用request trace_id。

### 19.1 对内错误映射

下表为网关DESIGN；Tencent列依据EXT-13及单接口资料。普通业务响应不暴露上游完整message、query、headers。

| reason | HTTP | retryable | 后续行为 |
|---|---:|---:|---|
| INVALID_REQUEST | 422 | false | 字段/枚举/额外参数拒绝 |
| TOKEN_INVALID / AUDIENCE_MISMATCH | 401 | false | 重新按正确凭据接入 |
| PERMISSION_DENIED / CLIENT_POLICY_MISMATCH | 403 | false | 无上游自动执行 |
| RESOURCE_NOT_ACCESSIBLE | 404 | false | 不区分不存在和无权给未授权者 |
| IDENTITY_UNBOUND | 409 | false | 配置已验证映射 |
| IDEMPOTENCY_CONFLICT / CONFIG_VERSION_CONFLICT / STATE_CONFLICT | 409 | false | 不覆盖既有状态 |
| AUTHORIZATION_CHANGED | 409 | false | 原确认/游标失效，重新经当前策略提交 |
| UPSTREAM_CAPABILITY_UNAVAILABLE | 409 | false | 换通道需管理员明确新授权，不自动fallback |
| UPSTREAM_PERMISSION_DENIED | 403 | false | 检查操作者与腾讯scope |
| UPSTREAM_REAUTH_REQUIRED | 409 | false | 仅明确授权失效触发重新授权 |
| UPSTREAM_AUTH_INVALID | 502 | false | 190303按AKSK/OAuth通道解释；OAuth可执行一次受控刷新复核，不无限循环 |
| UPSTREAM_SCOPE_UNSUPPORTED | 409 | false | 190325，检查能力/scopes |
| UPSTREAM_CLOCK_SKEW | 502 | false | 190300，修正时钟；不循环重试 |
| RATE_LIMITED | 429 | true | 短期额度；Job改WAITING_RATE，不耗失败次数 |
| UPSTREAM_DAILY_QUOTA_EXHAUSTED | 429 | true | 190311/190312；1小时后探测或明确人工恢复，不假设一分钟恢复 |
| CONTENT_PENDING | 202 | true | 转写30003等明确生成中→WAITING_CONTENT |
| CONTENT_EMPTY | 200 | false | 30002等接口明确无内容→EMPTY；不是假READY |
| CONTENT_NOT_ENABLED | 409 | false | 只有上游明确说明未开启才返回；不从空结果推断 |
| UPSTREAM_UNAVAILABLE / IDENTITY_SERVICE_UNAVAILABLE | 503 | true | 读取可退避；创建按是否已发送决定UNKNOWN |
| UPSTREAM_CONTRACT_ERROR / UPSTREAM_CONTENT_INCOMPLETE | 502 | false | 不发布错误数据，记录profile和字段诊断 |
| OUTCOME_UNKNOWN | 200（Operation读取） | false | 明确业务state，不能重试create |
| SOURCE_REMOVED / SOURCE_VERSION_CHANGED | 410 / 409 | false | 禁止旧文件续传；状态可通过重新授权查询更新 |
| RANGE_INVALID | 416 | false | 修正为有效单Range |
| ROLLBACK_FAILED | 500/命令exit1 | false | 保留备份、人工恢复 |

未列出的本地`*_CONFLICT`默认409非重试，输入校验类422，权限类403；新增reason须登记固定错误码表。未识别腾讯错误默认502 `UPSTREAM_CONTRACT_ERROR`；不得当成功，也不自动重新授权。

### 19.2 运行阈值与证据

RC2联调目标为在**固定测试环境4 vCPU、8GiB、PostgreSQL16、5000会议元数据、20并发内部请求、Backend mock延迟≤50ms**条件下：本地目录/operation状态P95≤500ms；创建/查询受理P95≤1000ms；这些是本稿测试阈值，不是腾讯端耗时承诺。腾讯内容生成耗时不计入本地API阈值。

指标包含：upstream_calls_by_operation、quota_wait_seconds、job_error_attempts、lease_lost、outcome_unknown、callback_ack_ms、delivery_attempts、permission_denials、source_health_age、download_bytes。告警：OUTCOME_UNKNOWN出现即记录高优先事件；Webhook提交失败连续3次、等待票据超300秒、读取Job失败均可追踪。图形监控大盘不作为RC2必需功能。


# 20. Acceptance Design Standard

归属：各Acceptance的Requirement Refs；REQ-EVID-001统一管理执行证据。下面所有测试路径、命令和输出都是**RC2目标验收合同**，不是宣称当前RC1已存在这些新增文件或本轮已执行。期望pytest exit 0是验收规则，实际值由运行记录填入。

Synthetic负责确定性算法、边界、失败注入及零副作用判断；Golden负责实际消费方、实际Backend、真实腾讯和真实MCP/数据库边界。二者均Required。测试中的`fixture_digest`来自测试仓内固定非敏感fixture的manifest；`authorized_reference_digest`来自批准的真实原始结果，仅在私有Evidence中保留，不在公开PRD写会议正文。


## A-ARCH-001-01 — 独立服务与接口优先边界：正向与恢复

### Requirement Refs
`REQ-ARCH-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
已运行Backend、Meeting、非Portal内部客户端并授予样本会议范围。

### When
执行员工兑换、创建、源查询、读取内容；采集网络轨迹。

### Then
所有业务步骤经REST完成，DB连接仅本服务库；没有Portal业务请求。

### Oracle
```text
portal_business_request_count==0 AND foreign_business_db_write_count==0 AND shared_domain_service_count==1
```

### Evidence
- test id：`TEST-A-ARCH-001-01`；command：`uv run pytest -q tests/acceptance/test_arch_001.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-ARCH-001-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-ARCH-001-02 — 独立服务与接口优先边界：负向拒绝

### Requirement Refs
`REQ-ARCH-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
接入配置携带OA目标或请求任意兄弟业务表写入；静态扫描部署与路由。

### When
执行范围检查，并尝试不存在的业务平台接口。

### Then
请求404/422；无兄弟业务数据改变；范围检查非0退出。

### Oracle
```text
forbidden_feature_route_count==0 AND foreign_business_source_digest_before==after
```

### Evidence
- test id：`TEST-A-ARCH-001-02`；command：`uv run pytest -q tests/acceptance/test_arch_001.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-ARCH-001-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-APP-001-01 — 双通道应用配置与确定性连接选择：正向与恢复

### Requirement Refs
`REQ-APP-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
同组织一个企业应用、一个OAuth应用，两名员工各有OAuth连接。

### When
分别查询适用资源，读取setup与诊断。

### Then
凭据隔离、回调使用内部receiver_id；探测单项独立。

### Oracle
```text
used_connection_ids==requested_connection_ids AND oauth_connection_count==2 AND secret_in_response_count==0
```

### Evidence
- test id：`TEST-A-APP-001-01`；command：`uv run pytest -q tests/acceptance/test_app_001.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-APP-001-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-APP-001-02 — 双通道应用配置与确定性连接选择：负向拒绝

### Requirement Refs
`REQ-APP-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
OAuth请求企业账户级列表；或选定连接返回权限拒绝，另有管理员连接。

### When
调用源查询并检查上游stub请求。

### Then
返回能力/权限错误，不借用管理员。

### Oracle
```text
cross_connection_fallback_count==0 AND unauthorized_upstream_call_count==0
```

### Evidence
- test id：`TEST-A-APP-001-02`；command：`uv run pytest -q tests/acceptance/test_app_001.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-APP-001-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-AUTH-001-01 — 内部应用认证与三类主体：正向与恢复

### Requirement Refs
`REQ-AUTH-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
员工A有效，系统客户端允许指定scope，MCP和REST受众不同。

### When
兑换员工票据、申请service票据并分别调用授权接口。

### Then
得到类型和范围正确的主体；禁用员工后下一请求被拒绝。

### Oracle
```text
employee_subject==backend_member_a AND service_member_id==null AND disabled_member_http==403
```

### Evidence
- test id：`TEST-A-AUTH-001-01`；command：`uv run pytest -q tests/acceptance/test_auth_001.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-AUTH-001-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-AUTH-001-02 — 内部应用认证与三类主体：负向拒绝

### Requirement Refs
`REQ-AUTH-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
错误client_secret、篡改员工字段、过期票据、REST票据调用MCP、重复refresh。

### When
参数化请求鉴权入口。

### Then
逐项401/403/422；不存在成功越权或明文腾讯Token。

### Oracle
```text
unexpected_token_count==0 AND accepted_wrong_audience_count==0 AND leaked_secret_count==0
```

### Evidence
- test id：`TEST-A-AUTH-001-02`；command：`uv run pytest -q tests/acceptance/test_auth_001.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-AUTH-001-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-AUTH-002-01 — 员工映射与操作/资源权限：正向与恢复

### Requirement Refs
`REQ-AUTH-002`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
A仅元数据，B含正文，C含下载，D为应用管理员但无资源读取。

### When
分别通过REST/MCP/下载/job结果访问同一会议；再撤销B。

### Then
矩阵匹配；B撤权后不再读缓存正文。

### Oracle
```text
acl_matrix_actual==expected AND post_revoke_body_bytes==0 AND admin_implicit_content_grants==0
```

### Evidence
- test id：`TEST-A-AUTH-002-01`；command：`uv run pytest -q tests/acceptance/test_auth_002.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-AUTH-002-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-AUTH-002-02 — 员工映射与操作/资源权限：负向拒绝

### Requirement Refs
`REQ-AUTH-002`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
跨组织ID、伪造participant、同名员工、已废弃源连接或DENY覆盖ALLOW。

### When
枚举列表/详情/正文/下载/事件入口。

### Then
均不暴露目标资源；只有审计副作用。

### Oracle
```text
denied_resource_leak_count==0 AND foreign_org_rows_changed==0
```

### Evidence
- test id：`TEST-A-AUTH-002-02`；command：`uv run pytest -q tests/acceptance/test_auth_002.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-AUTH-002-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-AUTH-003-01 — 腾讯OAuth授权与临时故障恢复：正向与恢复

### Requirement Refs
`REQ-AUTH-003`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
已过期access、有效refresh；第一次上游超时、第二次成功。

### When
并发两个Worker调用刷新。

### Then
仅受控刷新，先DEGRADED后ACTIVE，新票据原子替换。

### Oracle
```text
refresh_reauth_count==0 AND final_status==ACTIVE AND partial_token_row_count==0
```

### Evidence
- test id：`TEST-A-AUTH-003-01`；command：`uv run pytest -q tests/acceptance/test_auth_003.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-AUTH-003-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-AUTH-003-02 — 腾讯OAuth授权与临时故障恢复：负向拒绝

### Requirement Refs
`REQ-AUTH-003`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
state重放、换open_id、明确失效refresh、恶意redirect。

### When
参数化执行回调/刷新。

### Then
失效原因分别明确；重放0再次兑换；不能跨连接覆盖。

### Oracle
```text
replayed_exchange_count==0 AND foreign_connection_digest_before==after AND token_in_location_count==0
```

### Evidence
- test id：`TEST-A-AUTH-003-02`；command：`uv run pytest -q tests/acceptance/test_auth_003.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-AUTH-003-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-AUTH-004-01 — STS票据异步关联：正向与恢复

### Requirement Refs
`REQ-AUTH-004`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
企业应用待生成票据；模拟回调先到、响应后到以及正常顺序。

### When
触发生成并执行敏感读取。

### Then
两种顺序最终同一请求READY，读取注入正确STS。

### Oracle
```text
active_sts_count==1 AND correlation_match==true AND premature_ready_count==0
```

### Evidence
- test id：`TEST-A-AUTH-004-01`；command：`uv run pytest -q tests/acceptance/test_auth_004.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-AUTH-004-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-AUTH-004-02 — STS票据异步关联：负向拒绝

### Requirement Refs
`REQ-AUTH-004`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
来自其他应用/操作者、未知req_id、已过期票据或重复旧回调。

### When
投递这些回调并尝试内容读取。

### Then
不激活不匹配票据；读取等待或明确拒绝。

### Oracle
```text
invalid_active_ticket_count==0 AND plaintext_sts_in_audit_count==0
```

### Evidence
- test id：`TEST-A-AUTH-004-02`；command：`uv run pytest -q tests/acceptance/test_auth_004.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-AUTH-004-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-API-001-01 — 内部系统驱动的一次性会议创建：正向与恢复

### Requirement Refs
`REQ-API-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
第一期按 D-04、D-08、D-23 配置。TRUSTED_MEMBER 的主持人是当前员工。另一个客户端使用 HUMAN_CONFIRM。APPROVED_SERVICE 与 on_behalf 没有可执行授权。测试上游返回真实形状。

### When
TRUSTED_MEMBER 直接创建并轮询。HUMAN_CONFIRM 先确认再执行，确认由原内部系统员工接口在 10 分钟内完成。再发送一笔 APPROVED_SERVICE 创建。对成功受理的请求重复同一个 Idempotency-Key。

### Then
TRUSTED_MEMBER 不经过 Portal 即入队。HUMAN_CONFIRM 在确认前不发往腾讯。APPROVED_SERVICE 被拒绝且上游创建次数为 0。同一个幂等键只有一个 Operation，也只有一次上游创建。

### Oracle
```text
trusted_member_queued==true AND human_confirm_upstream_before_confirm==0 AND approved_service_upstream_create_count==0 AND unique_operation_count_per_key==1 AND upstream_create_count_per_key==1
```

### Evidence
- test id：`TEST-A-API-001-01`；command：`uv run pytest -q tests/acceptance/test_api_001.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-API-001-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-API-001-02 — 内部系统驱动的一次性会议创建：负向拒绝

### Requirement Refs
`REQ-API-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
SERVICE使用普通策略、Agent直接确认、伪造approved、参数更改后用旧hash、云录制参数非法组合。

### When
逐项发送请求并检查attempt表。

### Then
403/409/422；未授权情形0上游POST。

### Oracle
```text
unauthorized_create_attempt_count==0 AND unexpected_portal_redirect_count==0
```

### Evidence
- test id：`TEST-A-API-001-02`；command：`uv run pytest -q tests/acceptance/test_api_001.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-API-001-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-API-002-01 — 无需预导入的腾讯源会议查询：正向与恢复

### Requirement Refs
`REQ-API-002`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
本地为空，上游有3场会议，其中1场无录制、1场不在授权内。

### When
分别按ID和时间状态查询，并读取CATALOG。

### Then
SOURCE可取授权会议含无录制会议，CATALOG只标本地结果，权限过滤先于分页。

### Oracle
```text
source_visible_count==2 AND nonrecorded_meeting_present==true AND unauthorized_result_count==0
```

### Evidence
- test id：`TEST-A-API-002-01`；command：`uv run pytest -q tests/acceptance/test_api_002.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-API-002-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-API-002-02 — 无需预导入的腾讯源会议查询：负向拒绝

### Requirement Refs
`REQ-API-002`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
OAuth要求企业查询、改cursor筛选字段、跨员工重放、31天边界超1秒、填meeting_code代替providerID。

### When
参数化源查询。

### Then
拒绝不支持/无效输入；无自动fallback或元数据泄露。

### Oracle
```text
invalid_query_upstream_count==0 AND changed_cursor_accept_count==0
```

### Evidence
- test id：`TEST-A-API-002-02`；command：`uv run pytest -q tests/acceptance/test_api_002.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-API-002-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-API-003-01 — 按需会议详情与录制元数据：正向与恢复

### Requirement Refs
`REQ-API-003`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
映射存在、缓存已过期，上游会议有两个录制组、三个文件。

### When
并发ensure与一次cache。

### Then
ensure只有1个Job，完成后3文件关系正确；cache说明旧观察时间。

### Oracle
```text
active_refresh_job_count==1 AND recording_file_count==3 AND relation_mismatch_count==0
```

### Evidence
- test id：`TEST-A-API-003-01`；command：`uv run pytest -q tests/acceptance/test_api_003.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-API-003-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-API-003-02 — 按需会议详情与录制元数据：负向拒绝

### Requirement Refs
`REQ-API-003`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
无录制会议、错误文件归属、元数据权限者尝试获取分享密码或跨会议文件。

### When
调用元数据入口和故障fixture。

### Then
无录制返回空列表而非会议404；错误归属阻断；敏感字段不出现。

### Oracle
```text
empty_recordings_http==200 AND leaked_sensitive_metadata_count==0 AND invalid_relation_publish_count==0
```

### Evidence
- test id：`TEST-A-API-003-02`；command：`uv run pytest -q tests/acceptance/test_api_003.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-API-003-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-CONTENT-001-01 — 完整转写和腾讯原生纪要交付：正向与恢复

### Requirement Refs
`REQ-CONTENT-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
转写3页，页间含相同边界pid；纪要minute非空而todo空。

### When
获取并按客户端两页读取；检查发布事件。

### Then
边界去重且文本全量一致，纪要保留原类型；ready仅一次。

### Oracle
```text
published_paragraph_ids==expected_ids AND content_digest==fixture_digest AND ready_event_count_per_version==1
```

### Evidence
- test id：`TEST-A-CONTENT-001-01`；command：`uv run pytest -q tests/acceptance/test_content_001.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-CONTENT-001-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-CONTENT-001-02 — 完整转写和腾讯原生纪要交付：负向拒绝

### Requirement Refs
`REQ-CONTENT-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
more=true但无新pid、缺尾页、上游30003、未知模型结构、撤权后旧缓存存在。

### When
参数化读取失败路径。

### Then
没有半份READY；生成中等待；结构异常阻断；撤权不出正文。

### Oracle
```text
partial_ready_count==0 AND local_llm_call_count==0 AND denied_body_bytes==0
```

### Evidence
- test id：`TEST-A-CONTENT-001-02`；command：`uv run pytest -q tests/acceptance/test_content_001.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-CONTENT-001-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-DOWNLOAD-001-01 — 授权文件下载接口：正向与恢复

### Requirement Refs
`REQ-DOWNLOAD-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
授权音视频asset，文件1024字节，valid ticket。

### When
读取全量及Range bytes=0-99；核对计量。

### Then
200得到1024字节，206得到对应100字节，Content-Range和计量一致。

### Oracle
```text
full_digest==fixture_digest AND range_bytes==fixture_0_99 AND accounted_bytes==actual_sent
```

### Evidence
- test id：`TEST-A-DOWNLOAD-001-01`；command：`uv run pytest -q tests/acceptance/test_download_001.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-DOWNLOAD-001-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-DOWNLOAD-001-02 — 授权文件下载接口：负向拒绝

### Requirement Refs
`REQ-DOWNLOAD-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
其他主体重用ticket、过期、两段Range、跳转到私网、流中撤权或版本改变。

### When
参数化下载并记录停止点。

### Then
拒绝不合法读取；最多下一权限复核点停止，已发字节仍计量。

### Oracle
```text
unauthorized_new_stream_bytes==0 AND mixed_version_bytes==0 AND ssrf_attempt_count==0
```

### Evidence
- test id：`TEST-A-DOWNLOAD-001-02`；command：`uv run pytest -q tests/acceptance/test_download_001.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-DOWNLOAD-001-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-EVENT-001-01 — 腾讯回调接收与目标资源同步：正向与恢复

### Requirement Refs
`REQ-EVENT-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
30天前会议的smart.minutes成功事件两次、失败事件一次、回调先于本地映射。

### When
投递并执行Worker。

### Then
同成功事件只一个Inbox，已授权目标按ID查询，成功取内容后才ready；失败保留原因。

### Oracle
```text
unique_inbox_count_per_event==1 AND target_lookup_id==fixture_id AND premature_ready_count==0
```

### Evidence
- test id：`TEST-A-EVENT-001-01`；command：`uv run pytest -q tests/acceptance/test_event_001.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-EVENT-001-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-EVENT-001-02 — 腾讯回调接收与目标资源同步：负向拒绝

### Requirement Refs
`REQ-EVENT-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
签名错误、未知receiver、私有连接不在采集范围、DB在提交前断开。

### When
参数化回调。

### Then
签名错误不落库；提交失败不返回成功确认；不在范围不采集。

### Oracle
```text
invalid_inbox_count==0 AND ack_before_commit_count==0 AND unapproved_fetch_count==0
```

### Evidence
- test id：`TEST-A-EVENT-001-02`；command：`uv run pytest -q tests/acceptance/test_event_001.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-EVENT-001-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-EVENT-002-01 — 对内部系统的签名事件交付：正向与恢复

### Requirement Refs
`REQ-EVENT-002`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
一份READY资源、两个授权范围不同订阅者；授权者第一次收后响应丢失。

### When
发布并重试；接收端执行幂等消费。

### Then
只向有权订阅者发，重试相同event_id；接收端只提交一次。

### Oracle
```text
authorized_delivery_count==2 AND consumer_business_commit_count==1 AND unauthorized_delivery_count==0
```

### Evidence
- test id：`TEST-A-EVENT-002-01`；command：`uv run pytest -q tests/acceptance/test_event_002.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-EVENT-002-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-EVENT-002-02 — 对内部系统的签名事件交付：负向拒绝

### Requirement Refs
`REQ-EVENT-002`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
投递前撤权、篡改消息、错误签名、重放过期消息、目的地址重定向私网。

### When
参数化投递及示例验签器。

### Then
无权不推，签名器拒绝篡改/超时；网络边界不被绕过。

### Oracle
```text
post_revoke_delivery_count==0 AND invalid_signature_accepted==0 AND redirect_follow_count==0
```

### Evidence
- test id：`TEST-A-EVENT-002-02`；command：`uv run pytest -q tests/acceptance/test_event_002.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-EVENT-002-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-JOB-001-01 — 可续页作业、全局限流与错误语义：正向与恢复

### Requirement Refs
`REQ-JOB-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
默认间隔0.2秒、企业录制间隔6.1秒，3页转写/20页录制，两个Worker。

### When
执行到完成；第二页提交后重启Worker。

### Then
进度继续，无页0循环、无重复发布、总间隔符合限制。

### Oracle
```text
completed==true AND error_attempts_due_to_wait==0 AND requests_spacing_min>=configured_spacing AND committed_page_replayed_count==0
```

### Evidence
- test id：`TEST-A-JOB-001-01`；command：`uv run pytest -q tests/acceptance/test_job_001.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-JOB-001-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-JOB-001-02 — 可续页作业、全局限流与错误语义：负向拒绝

### Requirement Refs
`REQ-JOB-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
旧lease写checkpoint、more=true无进展、190311/190312、401权限错。

### When
故障注入并检查计划时间和状态。

### Then
旧lease0写；无进展明确失败；日额度不每分钟重试；权限错不无限重试。

### Oracle
```text
stale_lease_mutation_count==0 AND daily_quota_probe_interval_seconds>=3600 AND permission_retry_count==0
```

### Evidence
- test id：`TEST-A-JOB-001-02`；command：`uv run pytest -q tests/acceptance/test_job_001.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-JOB-001-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-MCP-001-01 — MCP复用会议接口与受限委托：正向与恢复

### Requirement Refs
`REQ-MCP-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
真实MCP SDK客户端、委托A可读不可下载、已完成REST样本。

### When
初始化、列工具、调用源查询/状态/正文；创建后通过内部系统确认。

### Then
符合协议、结果与REST一致，确认动作不经Agent工具。

### Oracle
```text
sdk_session_completed==true AND rest_mcp_policy_diff_count==0 AND agent_self_confirm_tools==0
```

### Evidence
- test id：`TEST-A-MCP-001-01`；command：`uv run pytest -q tests/acceptance/test_mcp_001.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-MCP-001-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-MCP-001-02 — MCP复用会议接口与受限委托：负向拒绝

### Requirement Refs
`REQ-MCP-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
列工具后撤权、错误aud、参数含operator_id、Agent调用confirm。

### When
再次执行工具调用。

### Then
拒绝，0未授权上游写操作。

### Oracle
```text
post_revoke_success_count==0 AND unauthorized_upstream_write_count==0
```

### Evidence
- test id：`TEST-A-MCP-001-02`；command：`uv run pytest -q tests/acceptance/test_mcp_001.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-MCP-001-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-OPS-001-01 — 最小配置与接口诊断：正向与恢复

### Requirement Refs
`REQ-OPS-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
应用配置齐全但STS未收到；基础列表可读。

### When
运行分层probe并导出setup。

### Then
基础项PASS，STS项BLOCKED，敏感内容不标PASS；路由标识稳定。

### Oracle
```text
probe_statuses==expected AND setup_receiver_id==stored_receiver_id
```

### Evidence
- test id：`TEST-A-OPS-001-01`；command：`uv run pytest -q tests/acceptance/test_ops_001.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-OPS-001-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-OPS-001-02 — 最小配置与接口诊断：负向拒绝

### Requirement Refs
`REQ-OPS-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
要求diagnostics.create或任意URL探测；只有配置字段而无请求结果。

### When
提交诊断并运行结果检查。

### Then
非法probe拒绝；没有真实结果不标联调通过。

### Oracle
```text
diagnostic_upstream_create_count==0 AND unsupported_probe_http==422 AND falsely_passed_probe_count==0
```

### Evidence
- test id：`TEST-A-OPS-001-02`；command：`uv run pytest -q tests/acceptance/test_ops_001.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-OPS-001-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-DATA-001-01 — 最小持久化、来源与缓存保留：正向与恢复

### Requirement Refs
`REQ-DATA-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
两条连接返回同腾讯ID、不同私有授权；受管缓存已到期。

### When
入库、分别读取、执行保留清理。

### Then
来源不合并；到期内容不可取，受管正文清理但墓碑可审计。

### Oracle
```text
origin_count==2 AND merged_acl_count==0 AND expired_read_bytes==0 AND unknown_owned_files_changed==0
```

### Evidence
- test id：`TEST-A-DATA-001-01`；command：`uv run pytest -q tests/acceptance/test_data_001.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-DATA-001-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-DATA-001-02 — 最小持久化、来源与缓存保留：负向拒绝

### Requirement Refs
`REQ-DATA-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
篡改内容对象、使来源连接失效、清理目录放入未知用户文件。

### When
读取和清理。

### Then
哈希失败阻止发布；授权失效不能读旧缓存；用户文件不动。

### Oracle
```text
tampered_content_delivered==0 AND user_owned_tree_digest_before==after
```

### Evidence
- test id：`TEST-A-DATA-001-02`；command：`uv run pytest -q tests/acceptance/test_data_001.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-DATA-001-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-TXN-001-01 — 创建不确定结果与跨系统事务边界：正向与恢复

### Requirement Refs
`REQ-TXN-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
记录attempt后腾讯创建成功，注入本地结果提交失败。

### When
重启Worker，再由授权运维核对同参数真实会议。

### Then
不重复POST，UNKNOWN可查，核对成功后1映射1成功事件。

### Oracle
```text
upstream_create_count==1 AND duplicate_meeting_count==0 AND reconciled_mapping_count==1
```

### Evidence
- test id：`TEST-A-TXN-001-01`；command：`uv run pytest -q tests/acceptance/test_txn_001.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-TXN-001-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-TXN-001-02 — 创建不确定结果与跨系统事务边界：负向拒绝

### Requirement Refs
`REQ-TXN-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
请求已送出后超时、worker在POST前后崩溃、核对填错误会议或rollback恢复失败。

### When
执行第23章注入矩阵。

### Then
不重发、不取消、不错误标成功；错误核对拒绝；备份不删。

### Oracle
```text
automatic_retry_post_count==0 AND automatic_cancel_count==0 AND retained_recovery_backup==true
```

### Evidence
- test id：`TEST-A-TXN-001-02`；command：`uv run pytest -q tests/acceptance/test_txn_001.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-TXN-001-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-MIGRATE-001-01 — RC1兼容升级与受管安装：正向与恢复

### Requirement Refs
`REQ-MIGRATE-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
干净RC1样本，包含旧client、旧订阅和已绑定资源。

### When
preview、apply、再次apply、执行旧合同回归。

### Then
首轮预期增量，次轮0diff；旧创建仍待确认、legacy事件名不变。

### Oracle
```text
second_apply_changed_bytes==0 AND old_contract_suite_exit==0 AND implicit_privilege_gain_count==0
```

### Evidence
- test id：`TEST-A-MIGRATE-001-01`；command：`uv run pytest -q tests/acceptance/test_migrate_001.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-MIGRATE-001-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-MIGRATE-001-02 — RC1兼容升级与受管安装：负向拒绝

### Requirement Refs
`REQ-MIGRATE-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
主仓库用户修改注册段、未知相同路径文件、备份介质失效。

### When
执行安装/回滚故障注入。

### Then
变更被阻止或回到T0；无法恢复时保留备份并非0退出。

### Oracle
```text
unowned_digest_before==after AND rollback_failure_exit!=0 AND recovery_artifact_exists==true
```

### Evidence
- test id：`TEST-A-MIGRATE-001-02`；command：`uv run pytest -q tests/acceptance/test_migrate_001.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-MIGRATE-001-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-SEC-001-01 — 凭据、网络、文件与内容边界：正向与恢复

### Requirement Refs
`REQ-SEC-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
固定上游、登记媒体host、32字节密钥、正常文件。

### When
调用正常业务并扫描全部响应、日志、文件布局。

### Then
只有允许网络/路径，凭据均加密且未输出。

### Oracle
```text
unexpected_network_target_count==0 AND plaintext_secret_matches==0 AND outside_root_write_count==0
```

### Evidence
- test id：`TEST-A-SEC-001-01`；command：`uv run pytest -q tests/acceptance/test_sec_001.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-SEC-001-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-SEC-001-02 — 凭据、网络、文件与内容边界：负向拒绝

### Requirement Refs
`REQ-SEC-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
路径../、symlink、DNS换成私网、恶意redirect、超大payload、nonce重放、正文提示注入。

### When
执行第18章安全矩阵。

### Then
逐项拒绝或只当数据；不改变授权、路由或执行命令。

### Oracle
```text
path_escape_count==0 AND arbitrary_execution_count==0 AND unauthorized_action_count==0
```

### Evidence
- test id：`TEST-A-SEC-001-02`；command：`uv run pytest -q tests/acceptance/test_sec_001.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-SEC-001-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-OBS-001-01 — 面向接口接入的审计和排障：正向与恢复

### Requirement Refs
`REQ-OBS-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
一次成功创建、一个限流读、一个权限拒绝和一次事件重试。

### When
按trace关联请求、Job、Operation与Delivery。；并运行第19.2节固定规模接口负载测试。

### Then
阶段链及错误语义可关联，脱敏字段完整。

### Oracle
```text
required_trace_fields_missing==0 AND trace_link_breaks==0 AND leaked_body_count==0 AND cached_read_p95_ms<=500 AND accepted_request_p95_ms<=1000
```

### Evidence
- test id：`TEST-A-OBS-001-01`；command：`uv run pytest -q tests/acceptance/test_obs_001.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-OBS-001-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-OBS-001-02 — 面向接口接入的审计和排障：负向拒绝

### Requirement Refs
`REQ-OBS-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
上游错误伪装200、日志含测试密钥或audit提交失败。

### When
执行错误和审计故障fixture。

### Then
业务错误不伪装成功；密钥被脱敏；本地关键写回滚。

### Oracle
```text
false_business_success_count==0 AND sensitive_log_matches==0 AND unlogged_local_business_commit_count==0
```

### Evidence
- test id：`TEST-A-OBS-001-02`；command：`uv run pytest -q tests/acceptance/test_obs_001.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-OBS-001-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-DOC-001-01 — 内部接入合同与可运行示例：正向与恢复

### Requirement Refs
`REQ-DOC-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
实现OpenAPI和固定合同；本地合成输入与已登记live manifest。

### When
比对schema；执行只读/机器/员工示例及验签测试。

### Then
合同一致；示例正确处理202而非当成功，事件签名可校验。

### Oracle
```text
contract_diff_count==0 AND examples_contract_exit==0 AND assumed_success_on_202_count==0
```

### Evidence
- test id：`TEST-A-DOC-001-01`；command：`uv run pytest -q tests/acceptance/test_doc_001.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-DOC-001-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-DOC-001-02 — 内部接入合同与可运行示例：负向拒绝

### Requirement Refs
`REQ-DOC-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
新增未文档字段、示例缺凭据、dry-run写文件或调用腾讯。

### When
运行合同/示例负向测试。

### Then
明确非0或0业务副作用，不产生虚构联调成功。

### Oracle
```text
unapproved_contract_change_count==0 AND dry_run_upstream_write_count==0 AND embedded_live_secret_count==0
```

### Evidence
- test id：`TEST-A-DOC-001-02`；command：`uv run pytest -q tests/acceptance/test_doc_001.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-DOC-001-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-EVID-001-01 — 真实内部消费方与腾讯联调发布门禁：正向与恢复

### Requirement Refs
`REQ-EVID-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
所有Required AC具备结构完整且可验证的证据，包括真实消费者。

### When
校验digest、关联test id、执行Gate。

### Then
全部PASS才exit0，结果能定位每个REQ。

### Oracle
```text
required_nonpass_count==0 AND broken_evidence_count==0 AND gate_exit==0
```

### Evidence
- test id：`TEST-A-EVID-001-01`；command：`uv run pytest -q tests/acceptance/test_evid_001.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-EVID-001-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-EVID-001-02 — 真实内部消费方与腾讯联调发布门禁：负向拒绝

### Requirement Refs
`REQ-EVID-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
任意Required缺失/跳过/受篡改，或仅提供历史测试数量和Mock截图。

### When
执行Gate。

### Then
FAIL或BLOCKED，process非0。

### Oracle
```text
gate_exit!=0 AND falsely_verified_requirement_count==0
```

### Evidence
- test id：`TEST-A-EVID-001-02`；command：`uv run pytest -q tests/acceptance/test_evid_001.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-EVID-001-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-GOV-001-01 — 需求语义、计划与评审门禁：正向与恢复

### Requirement Refs
`REQ-GOV-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
完整PRD、人工批准记录及具有全部字段的计划fixture。

### When
运行schema、引用与状态校验。

### Then
允许生成planned项，不允许直接verified。

### Oracle
```text
required_section_count==37 AND requirement_count==24 AND uncovered_norm_count==0 AND initial_todo_status==planned
```

### Evidence
- test id：`TEST-A-GOV-001-01`；command：`uv run pytest -q tests/acceptance/test_gov_001.py::test_positive`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-GOV-001-01/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-GOV-001-02 — 需求语义、计划与评审门禁：负向拒绝

### Requirement Refs
`REQ-GOV-001`；分类：SYNTHETIC；Release Gate：REQUIRED。

### Given
PRD为REVIEW，或删除hash范围/负向AC，或伪造evidence只写PASS。

### When
尝试生成计划或发布。

### Then
相应错误且无plan产物或发布成功状态。

### Oracle
```text
blocked_plan_created_count==0 AND fabricated_approval_count==0
```

### Evidence
- test id：`TEST-A-GOV-001-02`；command：`uv run pytest -q tests/acceptance/test_gov_001.py::test_negative`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-GOV-001-02/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-LIVE-001 — 真实内部应用的员工 OAuth 只读接入

### Requirement Refs
`REQ-APP-001`, `REQ-AUTH-001`, `REQ-AUTH-003`, `REQ-API-002`, `REQ-EVID-001`；分类：GOLDEN；Release Gate：REQUIRED。

### Given
Golden manifest已绑定实际消费方repo/commit，以及该员工自己的 OAuth 连接。目标会议由用户选为非敏感样本。不是 Mock。企业连接不是本项前置。

### When
由原内部应用后端使用已登记 client 调用员工 exchange，并按会议 ID 和该员工自己的时间窗做源查询。再发送一笔 CORP_WINDOW 查询。

### Then
OAuth 连接返回预期真实资源。消费方无需腾讯密钥，也不访问 Meeting Portal。CORP_WINDOW 被拒绝，且没有改用企业管理员身份的上游调用。

### Oracle
```text
live_transport_is_mock==false AND consumer_identity_verified==true AND oauth_connection_passed==true AND corp_window_rejected==true AND enterprise_fallback_count==0 AND portal_business_request_count==0
```

### Evidence
- test id：`TEST-A-LIVE-001`；command：`uv run pytest -q tests/live/test_internal_consumer.py::test_dual_channel_read --live-binding deploy/bindings/golden-consumer.json`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-LIVE-001/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-LIVE-002 — 真实内部系统创建与幂等

### Requirement Refs
`REQ-API-001`, `REQ-TXN-001`, `REQ-EVID-001`；分类：GOLDEN；Release Gate：REQUIRED。

### Given
真实 TRUSTED_MEMBER 客户端已获批准。主持人是当前员工。测试时间、创建数量和 business_ref 在 manifest 中显式批准。APPROVED_SERVICE 不在本项批准范围内。

### When
由内部系统以该员工身份创建一次性会议，重复同一个 Idempotency-Key 并轮询。

### Then
返回的会议在腾讯端核对存在，调用方业务关联一致。同一个幂等键只有一场会议。创建不要求 Meeting Portal，也不依赖 APPROVED_SERVICE。

### Oracle
```text
real_created_count==approved_expected_count AND duplicate_meeting_count==0 AND approved_service_upstream_create_count==0 AND consumer_business_ref_match==true AND tencent_id_matches_operation==true
```

### Evidence
- test id：`TEST-A-LIVE-002`；command：`uv run pytest -q tests/live/test_internal_consumer.py::test_create_and_idempotency --live-binding deploy/bindings/golden-consumer.json`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-LIVE-002/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-LIVE-003 — 真实 OAuth 原生会议结果

### Requirement Refs
`REQ-CONTENT-001`, `REQ-EVENT-001`, `REQ-EVID-001`；分类：GOLDEN；Release Gate：REQUIRED。

### Given
该员工自己的 OAuth 连接可用。已选一场该连接可见、云录制和腾讯纪要都已完成的非敏感会议。可访问完整上游参照结果。企业 STS 不是本项前置。

### When
由内部系统对该录制 ensure 读取完整转写和腾讯原生纪要，并等待作业完成。

### Then
转写段落与完整参照一致，纪要 profile 一致。只有完整性检查通过的版本产生 ready 事件。本项不生成、不等待企业 STS。

### Oracle
```text
sts_required==false AND transcript_digest==authorized_reference_digest AND minute_profile=={"llm":3,"text_type":1} AND premature_ready_count==0
```

### Evidence
- test id：`TEST-A-LIVE-003`；command：`uv run pytest -q tests/live/test_internal_consumer.py::test_sts_and_native_content --live-binding deploy/bindings/golden-consumer.json`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-LIVE-003/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-LIVE-004 — 真实内部通知与消费

### Requirement Refs
`REQ-EVENT-002`, `REQ-OBS-001`, `REQ-EVID-001`；分类：GOLDEN；Release Gate：REQUIRED。

### Given
真实内部系统HTTPS接收地址、签名密钥和去重存储已登记；有一份已授权就绪资源。

### When
投递签名事件；接收者第一次接收后故意丢失应答，再接收重试并读取资源。

### Then
内部系统签名通过、业务仅处理一次，投递状态可查；通知里无正文或腾讯凭据。

### Oracle
```text
consumer_signature_verified==true AND actual_consumer_commit_count_per_event==1 AND sensitive_event_field_count==0
```

### Evidence
- test id：`TEST-A-LIVE-004`；command：`uv run pytest -q tests/live/test_internal_consumer.py::test_signed_delivery --live-binding deploy/bindings/golden-consumer.json`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-LIVE-004/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-LIVE-005 — 真实文件下载与员工撤权

### Requirement Refs
`REQ-DOWNLOAD-001`, `REQ-AUTH-002`, `REQ-EVID-001`；分类：GOLDEN；Release Gate：REQUIRED。

### Given
A允许下载一个真实非敏感文件，B无权限；文件digest已由批准的参照下载获得。

### When
A全量与单Range下载；B尝试同ticket；撤销A后发起新的GET与续传。

### Then
A字节与参照相同；B和撤权后的新取流拒绝，未跨版本拼接内容。

### Oracle
```text
download_digest==authorized_reference_digest AND user_b_new_stream_bytes==0 AND post_revoke_new_stream_bytes==0 AND range_bytes_match==true
```

### Evidence
- test id：`TEST-A-LIVE-005`；command：`uv run pytest -q tests/live/test_internal_consumer.py::test_download_and_revoke --live-binding deploy/bindings/golden-consumer.json`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-LIVE-005/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-LIVE-006 — 真实智能体MCP会话

### Requirement Refs
`REQ-MCP-001`, `REQ-AUTH-001`, `REQ-AUTH-002`, `REQ-EVID-001`；分类：GOLDEN；Release Gate：REQUIRED。

### Given
批准的真实MCP客户端、固定SDK版本、有效AgentGrant和内部consent处理器；REST链路已通过。

### When
运行授权发现、初始化、tools/list、source query、Job轮询、纪要读取；撤销委托后再调用。

### Then
会话与业务成功可关联，撤销后拒绝；不存在Agent自确认或腾讯Token透传。

### Oracle
```text
sdk_session_trace_present==true AND real_tool_success_count>=3 AND revoked_tool_success_count==0 AND tencent_token_exposed==false
```

### Evidence
- test id：`TEST-A-LIVE-006`；command：`uv run pytest -q tests/live/test_mcp_consumer.py::test_real_session --live-binding deploy/bindings/golden-consumer.json`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-LIVE-006/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


## A-LIVE-007 — 真实PostgreSQL与主仓库集成回归

### Requirement Refs
`REQ-ARCH-001`, `REQ-JOB-001`, `REQ-MIGRATE-001`, `REQ-DOC-001`, `REQ-EVID-001`；分类：GOLDEN；Release Gate：REQUIRED。

### Given
固定主仓库基线或已审查目标commit、真实PostgreSQL16、两个Worker、干净受管工作区和已备份RC1配置。

### When
执行迁移、重复安装、Backend身份回归、并发Job/令牌/额度测试、内部消费者API合同测试。

### Then
真实数据库锁及租约有效；非受管源码保持不变；旧合同和新接口通过，不用SQLite替代。

### Oracle
```text
database_engine==postgresql AND concurrent_workers==2 AND duplicate_job_commits==0 AND user_owned_digest_before==after AND legacy_suite_exit==0 AND consumer_suite_exit==0
```

### Evidence
- test id：`TEST-A-LIVE-007`；command：`uv run pytest -q tests/live/test_postgres_consumer.py::test_multiservice_integration --live-binding deploy/bindings/golden-consumer.json`。
- exit code：期望0；pre/post digest：按第13章输出业务范围快照，即使均无变更也记录摘要；只有无受管状态的协议测试可用scope=NONE并明确原因。
- artifact：`reports/acceptance/<run_id>/A-LIVE-007/evidence.json`、`assertions.json`、`stdout.log`、`scope-manifest.json`。
- digest：Evidence引用文件均记录实际SHA-256；实际HTTP结果、计数、时间和布尔Oracle写入assertions，不仅填写PASS。


# 21. Acceptance Input Matrix

归属：各高风险Requirement。以下每个cell对应正向/负向Acceptance中的一个参数化case；`N/A`须有本表明示原因，不能默默漏测。

| Case | 创建/幂等 | 源查询/内容 | 身份/授权 | 回调/投递 | 安装/事务 |
|---|---|---|---|---|---|
| normal | 三策略合法状态 | 单页和完整多页 | 员工/系统/Agent合法 | 已授权ready | 干净RC1升级 |
| empty | 空subject拒绝 | 空会议/录制不是失败；明确EMPTY | 空连接scope=无权限 | 空payload不赋权 | 空diff二次apply0变化 |
| missing | 无key/host拒绝 | 缺provider ID或window拒绝 | 缺Token/映射拒绝 | 缺签名拒绝 | 无ownership不覆盖 |
| existing | 同key同参数同Operation | 已有版本同digest复用 | 已有Grant去重 | 相同事件同Inbox | 现有受管段按digest升级 |
| duplicate | 同时100请求只1attempt | 边界pid去重 | refresh重用拒绝 | 响应丢失event_id不变 | 同迁移不能并发提交 |
| drifted | 确认hash不同拒绝 | source/cursor版本变更拒绝 | policy_version变更拒绝 | 同event_id不同payload隔离 | 用户编辑受管段BLOCK |
| partial | 已发请求无响应UNKNOWN | 末页失败不READY | 新票据写一半不得启用 | Inbox提交失败不ack | stage部分失败回到T0 |
| invalid | approved/operator_id额外字段拒绝 | 非法时间/limit/cursor拒绝 | 错org/aud/client | 错签名/未知receiver | ../symlink/未知schema |
| boundary | subject256/257、start过期、key128/129 | 窗口31天/31天+1秒、limit1/100/101 | token刚到期、空scope | 1MiB/超1字节、签名±300秒 | 同内容不同owner拒绝 |
| retry | 仅重取Operation不重POST | quota等待续页 | 临时刷新故障后恢复 | 8次投递上限 | 二次apply不增量 |
| failure | 远端成功本地提交错 | 中页超时/分页无进展 | Backend不可达fail closed | 回调DB失败/收件者5xx | before/after write错误 |
| rollback | 本地T0与远端不可回滚区别 | 旧内容版本保留 | 旧票据保留但不越期用 | 事件不早于业务提交 | 回滚失败保留备份 |

所有ACTION的授权负向覆盖REST、MCP、Worker、download、job result、delivery六条路径；READ操作无需“删除腾讯会议”回滚case，其确定Oracle是腾讯业务源digest不变。

# 22. Negative Acceptance

每个REQ的N3均绑定自己的`A-<同slug>-02`，不是一个通用安全用例覆盖所有禁止行为。以下列出最重要的禁止项定位：

| 禁止行为 | 负向Acceptance | 必须观测的拒绝/不变 |
|---|---|---|
| 以Portal为内部应用业务必经步骤 | A-ARCH-001-02、A-API-001-02 | 无强制Portal跳转 |
| OAuth失败换企业管理员连接 | A-APP-001-02 | fallback count=0 |
| 伪造employee_id/approved | A-AUTH-001-02、A-API-001-02 | 401/403/422且0外部创建 |
| 元数据权推导正文/下载权 | A-AUTH-002-02 | 正文字节=0 |
| 临时超时直接重新授权 | A-AUTH-003-02及01恢复case | 不进入REAUTH_REQUIRED |
| 把STS请求号当票据 | A-AUTH-004-02 | 敏感读取不得使用req_id当header |
| 用录制列表冒充全部会议 | A-API-002-02 | 非录制会议仍可查询，scope明确 |
| 部分转写冒充READY | A-CONTENT-001-02 | partial READY=0 |
| 任意URL/签名链接直接暴露 | A-DOWNLOAD-001-02 | SSRF与链接泄露=0 |
| 未提交Inbox先确认 | A-EVENT-001-02 | ack_before_commit=0 |
| 声称exactly-once跨网络交付 | A-EVENT-002-02 | 重投相同event_id；消费去重证据 |
| 无人重发不确定创建 | A-TXN-001-02 | second POST=0 |
| 升级覆盖用户文件 | A-MIGRATE-001-02 | user_owned_digest相等 |
| 历史测试数量代替真实证据 | A-EVID-001-02 | Gate非0 |
| REVIEW直接变计划verified | A-GOV-001-02 | 不生成该计划或拒绝状态 |

# 23. Failure Injection

归属：REQ-TXN-001、REQ-JOB-001、REQ-EVENT-001/002、REQ-AUTH-003/004、REQ-MIGRATE-001。每项在相应Acceptance的参数化case中执行并输出注入位置。

| FI ID / 注入点 | 预期postcondition | Acceptance |
|---|---|---|
| FI-01 before first DB write | 业务范围等于T0，0上游创建 | A-TXN-001-02 |
| FI-02 after Operation row before commit | 无可见孤立Operation/Job；幂等重试可受理 | A-TXN-001-02 |
| FI-03 after attempt commit before HTTP send | 恢复时保守UNKNOWN；不能无证据重发 | A-TXN-001-02 |
| FI-04 Tencent接收请求后连接断开 | OUTCOME_UNKNOWN；只查询/核对，不再POST | A-TXN-001-02 |
| FI-05 response received before DB result commit | 保留恢复记录，0重复创建；后续核对可链接 | A-TXN-001-01 |
| FI-06 after第N页checkpoint commit | 重启从N后位置继续；前N页不重复重抓 | A-JOB-001-01 |
| FI-07 during content verify | 旧发布指针不变；新staging不可读 | A-CONTENT-001-02 |
| FI-08 after对象rename before Asset commit | 无READY；保留明确孤儿引用24小时再受管清理 | A-DATA-001-02 |
| FI-09 Inbox commit前DB失败 | 回腾讯5xx，重试后只1Inbox | A-EVENT-001-02 |
| FI-10 consumer已提交、回执丢失 | 同event_id重投，消费方业务commit只1次 | A-EVENT-002-01、A-LIVE-004 |
| FI-11 OAuth refresh短时5xx | DEGRADED，保留refresh，后续可恢复 | A-AUTH-003-01 |
| FI-12 STS回调早于req_id关联 | 加密缓冲，匹配前不启用，匹配后READY | A-AUTH-004-01 |
| FI-13 old lease提交 | fence拒绝，checkpoint未变 | A-JOB-001-02 |
| FI-14 during install commit | 受管范围恢复T0，用户字节不变 | A-MIGRATE-001-02 |
| FI-15 during rollback恢复 | ROLLBACK_FAILED，保留备份和恢复manifest，exit非0 | A-MIGRATE-001-02、A-TXN-001-02 |
| FI-16 请求合法后、Worker执行前撤权 | 执行前拒绝且0新腾讯写；已发出的请求不能虚构回收 | A-AUTH-002-01、A-API-001-02 |

# 24. Evidence Contract

## 24.1 Evidence 不是状态标签

归属：REQ-EVID-001。Evidence schema为JSON Schema 2020-12、版本1.0、additionalProperties=false。必填：

```text
acceptance_id: string，必须存在于第20章
status: PASS | FAIL | SKIPPED | BLOCKED
requirement_ids: 非空REQ数组
test_ids: 非空TEST数组
command: 实际命令字符串
exit_code: integer|null；PASS时必须0
oracle: {expression,expected,actual,passed}；passed为bool
repo: {url,commit,branch,dirty,patch_digest,source_archive_sha256}
consumer: {manifest_digest,repo,commit,dirty,patch_digest}|null；Golden必填
timestamp: RFC3339 UTC
run_id: UUID字符串
tool_versions: {python,pytest,uv,postgres,mcp_sdk}；不适用项用null并在reason说明
pre_snapshot: {scope,manifest_digest}|null
post_snapshot: {scope,manifest_digest}|null
evidence_files: [{path,sha256,size_bytes}]
reason: string|null
injection_point: string|null
```

PASS还要求expected/actual能计算为一致，所有evidence_files实际存在且digest相符。BLOCKED允许命令未执行、exit_code=null，但必须reason明确且Release不通过。status不能由实现提交消息或界面截图直接填写PASS。

## 24.2 Evidence Integrity

repo.commit为实际checkout的完整40位SHA；无Git的源码包使用真实source_archive_sha256并将commit设null，**这种包证据只用于静态合成检查，不能替代Golden的真实repo绑定**。记录dirty及补丁digest；目标生产Golden默认要求clean=true，批准的安装增量作为受管变更另记before/after，不掩盖未跟踪文件。

Evidence文件存入`reports/acceptance/{run_id}/{acceptance_id}/`，run目录不可覆写。私有原始HTTP/body只在批准的私有Evidence库保留；对外报告保留脱敏身份别名、计数、digest和资源版本，不能公开真实会议正文、密钥或下载URL。

第13章定义scope快照与manifest算法。任何文件丢失、test_id无法关联、hash不符或实际Oracle失败，证据状态不得PASS。

# 25. Release Gate

归属：REQ-EVID-001、REQ-GOV-001。定义三个结果，不互相代替：

| Gate | 用途 | PASS条件 |
|---|---|---|
| PRD_STRUCTURAL_GATE | 文档结构/引用检查 | 37章、24REQ、各完整单元、AC/TEST/EVID引用与Oracle齐全；不是功能测试 |
| PLAN_GATE | 允许编制实施计划 | PRD批准记录有效，status=APPROVED_FOR_PLAN，无SPEC_SEMANTIC_GAP |
| RC2_INTEGRATION_RELEASE_GATE | 宣布达到本PRD联调目的 | 第20章全部55项Required为PASS，真实消费方7项均有实际证据 |

`SKIPPED != PASS`，`BLOCKED != PASS`。Required任一非PASS或缺Evidence，RC2 Gate结论FAIL，process exit=1；工具自身异常exit=2同样不是PASS。可在全部Gate前做只读探测，但不得对外宣称“联调完成”。

RC2通过不等于正式生产SLA、容量和业务审批上线已批准。部署操作者仍应按组织流程批准生产启用；本PRD不增加另一个员工审批产品。

# 26. Golden Consumer / Real-world Acceptance

归属：REQ-EVID-001。**真实消费方是原内部应用服务器，不是Meeting Portal，也不是新写的Mock演示页面。** 用户尚未提供该内部系统的实际repo/运行端点，本稿不虚构其名称、SHA或线上证据。

通过强类型部署输入解决绑定：`deploy/bindings/golden-consumer.json`包含第9章S-BINDING，额外要求consumer_commit为完整Git SHA且由实际checkout验证；consumer_repo由内部系统负责人提供；非Git交付需提供不可变构建digest及其与源码的组织签署对应关系。无任一可验证身份时Golden=BLOCKED，不是推断成功。

真实腾讯调用只能从已列入腾讯 IP 白名单的网关公网出口发起（D-06）。该地址是出口 NAT 地址，不是员工电脑地址，也不是入口负载均衡地址。开发机未获授权，本机只运行合成传输。出口 IP 与消费方身份写入部署绑定，不写入本稿正文。绑定或授权出口缺失时，现场验收保持 BLOCKED，本机跳过或失败都不能写成联调 PASS。

### 26.1 必需现场记录

| 项目 | 采集责任 | Oracle |
|---|---|---|
| 消费方repo identity、HEAD SHA、clean/dirty | 内部系统负责人/验收工具 | 与实际checkout一致，不用移动main代替 |
| Meeting/Backend运行commit、镜像digest | 网关运维 | 与构建清单相符 |
| before/after snapshot | 验收工具 | 受管变更可解释，非受管范围digest相等 |
| business source digest | 内部系统+腾讯只读参照 | 只读case前后稳定范围相等；写case差集恰为批准创建 |
| user-owned content digest | 主仓库集成检查器 | 安装段外相等 |
| 双通道和员工映射 | 应用管理员 | 实际授权响应匹配绑定 |
| 非敏感已知会议/文件及原始参照 | 测试负责人 | gateway结果digest等于已批准参照 |
| 实际回调/通知/MCP会话 | 内部系统负责人 | 有网络和应用接收证据，不只SDK数据结构校验 |

上游资源会随真实会议推进而自然变化，business source digest的比较范围固定为fixture选定字段（会议标识、subject、预定时间、创建者、录制文件标识和已生成内容版本）；实时参会人数、观察时间不加入“只读不变”的比较。排除字段在scope manifest明确列出，不能测试失败后临时排除。

### 26.2 按消费者行为推进的交付顺序

| 包 | 业务可见交付 | 主要Requirement | 不允许替代 |
|---|---|---|---|
| A 内部调用会议接口 | 凭据兑换→可信创建→按源查询→Operation/Job结果 | APP/AUTH/API/TXN | 仅Portal页面截图 |
| B 内部取得结果与通知 | 录制→转写/纪要→下载→内部事件 | CONTENT/DOWNLOAD/EVENT/JOB | 只收到腾讯Webhook |
| C 智能体与接入交付 | 相同服务MCP调用、合同/示例、真实集成回归 | MCP/DOC/MIGRATE/EVID | 仅合成Mock成功 |

这些是产品交付顺序，不是本轮生成的实施计划；权限与来源检查从A开始，不能留到最后补。

# 27. Requirement Traceability Matrix

每行都是REQUIRED；N1/N2→01，N3→02；相关Golden由第20章Requirement Refs反向关联。Test/Evidence是目标合同标识，不代表已执行。


| Requirement | Invariant | Acceptance | Test | Evidence | Release Gate |
|---|---|---|---|---|---|
| REQ-ARCH-001 | INV-ARCH-001-01 | A-ARCH-001-01 / A-ARCH-001-02 | TEST-A-ARCH-001-01 / TEST-A-ARCH-001-02 | EVID-A-ARCH-001-01 / EVID-A-ARCH-001-02 | REQUIRED |
| REQ-APP-001 | INV-APP-001-01 | A-APP-001-01 / A-APP-001-02 | TEST-A-APP-001-01 / TEST-A-APP-001-02 | EVID-A-APP-001-01 / EVID-A-APP-001-02 | REQUIRED |
| REQ-AUTH-001 | INV-AUTH-001-01 | A-AUTH-001-01 / A-AUTH-001-02 | TEST-A-AUTH-001-01 / TEST-A-AUTH-001-02 | EVID-A-AUTH-001-01 / EVID-A-AUTH-001-02 | REQUIRED |
| REQ-AUTH-002 | INV-AUTH-002-01 | A-AUTH-002-01 / A-AUTH-002-02 | TEST-A-AUTH-002-01 / TEST-A-AUTH-002-02 | EVID-A-AUTH-002-01 / EVID-A-AUTH-002-02 | REQUIRED |
| REQ-AUTH-003 | INV-AUTH-003-01 | A-AUTH-003-01 / A-AUTH-003-02 | TEST-A-AUTH-003-01 / TEST-A-AUTH-003-02 | EVID-A-AUTH-003-01 / EVID-A-AUTH-003-02 | REQUIRED |
| REQ-AUTH-004 | INV-AUTH-004-01 | A-AUTH-004-01 / A-AUTH-004-02 | TEST-A-AUTH-004-01 / TEST-A-AUTH-004-02 | EVID-A-AUTH-004-01 / EVID-A-AUTH-004-02 | REQUIRED |
| REQ-API-001 | INV-API-001-01 | A-API-001-01 / A-API-001-02 | TEST-A-API-001-01 / TEST-A-API-001-02 | EVID-A-API-001-01 / EVID-A-API-001-02 | REQUIRED |
| REQ-API-002 | INV-API-002-01 | A-API-002-01 / A-API-002-02 | TEST-A-API-002-01 / TEST-A-API-002-02 | EVID-A-API-002-01 / EVID-A-API-002-02 | REQUIRED |
| REQ-API-003 | INV-API-003-01 | A-API-003-01 / A-API-003-02 | TEST-A-API-003-01 / TEST-A-API-003-02 | EVID-A-API-003-01 / EVID-A-API-003-02 | REQUIRED |
| REQ-CONTENT-001 | INV-CONTENT-001-01 | A-CONTENT-001-01 / A-CONTENT-001-02 | TEST-A-CONTENT-001-01 / TEST-A-CONTENT-001-02 | EVID-A-CONTENT-001-01 / EVID-A-CONTENT-001-02 | REQUIRED |
| REQ-DOWNLOAD-001 | INV-DOWNLOAD-001-01 | A-DOWNLOAD-001-01 / A-DOWNLOAD-001-02 | TEST-A-DOWNLOAD-001-01 / TEST-A-DOWNLOAD-001-02 | EVID-A-DOWNLOAD-001-01 / EVID-A-DOWNLOAD-001-02 | REQUIRED |
| REQ-EVENT-001 | INV-EVENT-001-01 | A-EVENT-001-01 / A-EVENT-001-02 | TEST-A-EVENT-001-01 / TEST-A-EVENT-001-02 | EVID-A-EVENT-001-01 / EVID-A-EVENT-001-02 | REQUIRED |
| REQ-EVENT-002 | INV-EVENT-002-01 | A-EVENT-002-01 / A-EVENT-002-02 | TEST-A-EVENT-002-01 / TEST-A-EVENT-002-02 | EVID-A-EVENT-002-01 / EVID-A-EVENT-002-02 | REQUIRED |
| REQ-JOB-001 | INV-JOB-001-01 | A-JOB-001-01 / A-JOB-001-02 | TEST-A-JOB-001-01 / TEST-A-JOB-001-02 | EVID-A-JOB-001-01 / EVID-A-JOB-001-02 | REQUIRED |
| REQ-MCP-001 | INV-MCP-001-01 | A-MCP-001-01 / A-MCP-001-02 | TEST-A-MCP-001-01 / TEST-A-MCP-001-02 | EVID-A-MCP-001-01 / EVID-A-MCP-001-02 | REQUIRED |
| REQ-OPS-001 | INV-OPS-001-01 | A-OPS-001-01 / A-OPS-001-02 | TEST-A-OPS-001-01 / TEST-A-OPS-001-02 | EVID-A-OPS-001-01 / EVID-A-OPS-001-02 | REQUIRED |
| REQ-DATA-001 | INV-DATA-001-01 | A-DATA-001-01 / A-DATA-001-02 | TEST-A-DATA-001-01 / TEST-A-DATA-001-02 | EVID-A-DATA-001-01 / EVID-A-DATA-001-02 | REQUIRED |
| REQ-TXN-001 | INV-TXN-001-01 | A-TXN-001-01 / A-TXN-001-02 | TEST-A-TXN-001-01 / TEST-A-TXN-001-02 | EVID-A-TXN-001-01 / EVID-A-TXN-001-02 | REQUIRED |
| REQ-MIGRATE-001 | INV-MIGRATE-001-01 | A-MIGRATE-001-01 / A-MIGRATE-001-02 | TEST-A-MIGRATE-001-01 / TEST-A-MIGRATE-001-02 | EVID-A-MIGRATE-001-01 / EVID-A-MIGRATE-001-02 | REQUIRED |
| REQ-SEC-001 | INV-SEC-001-01 | A-SEC-001-01 / A-SEC-001-02 | TEST-A-SEC-001-01 / TEST-A-SEC-001-02 | EVID-A-SEC-001-01 / EVID-A-SEC-001-02 | REQUIRED |
| REQ-OBS-001 | INV-OBS-001-01 | A-OBS-001-01 / A-OBS-001-02 | TEST-A-OBS-001-01 / TEST-A-OBS-001-02 | EVID-A-OBS-001-01 / EVID-A-OBS-001-02 | REQUIRED |
| REQ-DOC-001 | INV-DOC-001-01 | A-DOC-001-01 / A-DOC-001-02 | TEST-A-DOC-001-01 / TEST-A-DOC-001-02 | EVID-A-DOC-001-01 / EVID-A-DOC-001-02 | REQUIRED |
| REQ-EVID-001 | INV-EVID-001-01 | A-EVID-001-01 / A-EVID-001-02 | TEST-A-EVID-001-01 / TEST-A-EVID-001-02 | EVID-A-EVID-001-01 / EVID-A-EVID-001-02 | REQUIRED |
| REQ-GOV-001 | INV-GOV-001-01 | A-GOV-001-01 / A-GOV-001-02 | TEST-A-GOV-001-01 / TEST-A-GOV-001-02 | EVID-A-GOV-001-01 / EVID-A-GOV-001-02 | REQUIRED |



### 27.1 公共合同归属矩阵

| 章节 | Owner Requirement / 验收 |
|---|---|
| 0–6目的/范围/边界 | REQ-ARCH-001、REQ-GOV-001 |
| 7状态事实源 | REQ-DATA-001、REQ-AUTH-002、REQ-TXN-001 |
| 8状态机 | 各生命周期Requirement，A-同slug-01/02 |
| 9Schema/API/默认值 | REQ-DOC-001、各AUTH/API/CONTENT/EVENT/MCP |
| 11副作用 | REQ-TXN-001、REQ-SEC-001、REQ-DOC-001 |
| 12/16 ownership/迁移 | REQ-MIGRATE-001、REQ-DATA-001 |
| 13哈希 | REQ-API-001、REQ-DATA-001、REQ-EVID-001 |
| 14/15事务与冲突 | REQ-TXN-001、REQ-JOB-001、REQ-MIGRATE-001 |
| 17外部契约 | REQ-APP-001、REQ-AUTH-003/004、REQ-JOB-001、REQ-DOC-001 |
| 18/19安全可观测性 | REQ-SEC-001、REQ-OBS-001 |
| 20–27验收与证据 | 各REQ和REQ-EVID-001 |
| 28–36计划/评审/完成定义 | REQ-GOV-001 |

任何N项缺AC、任何AC缺test或Oracle，文档门禁BLOCKED；Required AC无有效Evidence则发布BLOCKED/FAIL，不能以本表填满代替执行。

### 27.2 Golden Consumer追踪矩阵

| Acceptance | Requirement Refs | Test | Evidence | Release Gate |
|---|---|---|---|---|
| A-LIVE-001 | REQ-APP-001, REQ-AUTH-001, REQ-AUTH-003, REQ-API-002, REQ-EVID-001 | TEST-A-LIVE-001 | EVID-A-LIVE-001 | REQUIRED |
| A-LIVE-002 | REQ-API-001, REQ-TXN-001, REQ-EVID-001 | TEST-A-LIVE-002 | EVID-A-LIVE-002 | REQUIRED |
| A-LIVE-003 | REQ-AUTH-004, REQ-CONTENT-001, REQ-EVENT-001, REQ-EVID-001 | TEST-A-LIVE-003 | EVID-A-LIVE-003 | REQUIRED |
| A-LIVE-004 | REQ-EVENT-002, REQ-OBS-001, REQ-EVID-001 | TEST-A-LIVE-004 | EVID-A-LIVE-004 | REQUIRED |
| A-LIVE-005 | REQ-DOWNLOAD-001, REQ-AUTH-002, REQ-EVID-001 | TEST-A-LIVE-005 | EVID-A-LIVE-005 | REQUIRED |
| A-LIVE-006 | REQ-MCP-001, REQ-AUTH-001, REQ-AUTH-002, REQ-EVID-001 | TEST-A-LIVE-006 | EVID-A-LIVE-006 | REQUIRED |
| A-LIVE-007 | REQ-ARCH-001, REQ-JOB-001, REQ-MIGRATE-001, REQ-DOC-001, REQ-EVID-001 | TEST-A-LIVE-007 | EVID-A-LIVE-007 | REQUIRED |

这些行和前述48项合成验收共同构成55项发布清单；没有运行证据时状态仍为BLOCKED。

# 28. Plan Generation Contract

归属：REQ-GOV-001。仅`status=APPROVED_FOR_PLAN`且第 1.2 节批准记录的 `prd_digest` 按该节算法校验通过时，允许生成`.plan.md`。本稿已是 APPROVED_FOR_PLAN。本轮仍不在本稿内生成实施计划或产品源码。

## 28.1 Semantic Gap Check

验证状态、默认、选择语义、hash范围、事务、权限、失败、ownership和Oracle均有唯一描述。若评审决定改变策略或字段，先修PRD并回到REVIEW，不在计划里静默修改。部署凭据等属于有schema的输入，其缺失行为为BLOCKED。

## 28.2 Requirement Coverage Check

24个REQ都具有ID、N项、AC、Failure、Oracle与Evidence；新添需求也必须使用第10章完整结构。不得以“其他同上”省略高风险需求的失败语义。

## 28.3 Side Effect Check

每个计划mutation引用第11章允许作用域和第12章ownership；read-only必须说明是否指腾讯业务源、Meeting数据库还是文件树。

## 28.4 State Authority Check

每个新增持久字段归属第7章中的状态类型与唯一writer，重复SOT阻止计划。

## 28.5 Failure-path Check

计划涉及retry、rollback、atomic、recover的任务引用第23章具体注入ID；外部创建不能用DB回滚作为远程回滚证明。

# 29. `.plan.md` 输出标准

归属：REQ-GOV-001。下面是计划字段标准，不是本次已批准执行任务：

```yaml
id: "PLAN-UNIT-ID"
requirement_refs: ["已存在的REQ-ID"]
acceptance_refs: ["已存在的A-ID"]
files_or_symbols: ["实际可定位路径或明确新增路径"]
implementation_goal: "一个可独立验证的结果"
preconditions: ["可机器检查的输入状态"]
state_transition: "本PRD已定义的前后状态"
side_effect_scope: ["本PRD允许的ROW/FILE/SECTION范围"]
failure_cases: ["本PRD的F/ FI-ID"]
verification: ["实际执行命令及Oracle"]
status: planned
evidence: []
commit_policy: post_review
```

status只有planned/implemented/verified/blocked。代码写完至多implemented；verified必须具备对应Acceptance的执行Evidence。提交单元不得混合未批准PRD、代码实现和伪造已验证Roadmap状态。

# 30. Code Review Contract

归属：REQ-GOV-001；评审顺序固定为：Requirement实现 → State Authority → Side Effect → Failure postcondition → Ownership → Drift → AC覆盖 → Evidence有效性 → 边界输入 → Code quality。

对本项目新增五项明确检查：创建是否仍被Portal硬依赖；SOURCE是否真正查询腾讯而非本地目录；SERVICE是否被静默视为管理员员工；事件是否仅到达就宣称内容READY；MCP是否绕开了REST的PermissionService。任一为真则相应REQ FAIL。

评审记录写repo commit、REQ/AC引用、严重性、证据、结论和处理状态，不用“代码看起来可用”代替Oracle。与消费者联调有关的意见由内部系统接口负责人参与，不仅由网关实现者自评。

# 31. PRD Quality Gate

下面区分“本文结构检查”与“尚需人工批准/执行”的项；勾选不代表产品功能已实现。

## Architecture

- [x] Goal唯一：腾讯会议接入，为内部系统提供接口。
- [x] Scope/Non-goal明确，员工工作台与OA流程在范围外。
- [x] Backend身份、Meeting权限、内部系统业务Owner分离。
- [x] System Boundary及输入信任范围已列出。

## State

- [x] 第7章已列出持久状态类别、SOT与writer；语义覆盖仍须评审。
- [x] Desired/Observed/Resolved/Last Applied/Runtime/Evidence分离。
- [x] 创建、授权、票据、内容、作业、事件、下载状态机与恢复路径已定义。

## Semantics

- [x] 创建策略、cache/ensure、SOURCE/CATALOG、空范围和省略字段规则明确。
- [x] hash、identity、cursor、事件签名定义了编码、排序及范围。
- [x] 冲突默认BLOCK/PRESERVE，不使用last-writer-wins。

## Side Effects

- [x] 接口、CLI、MCP、Worker与live测试有副作用合同。
- [x] 腾讯只读与本地缓存/审计写入明确分离。

## Failure

- [x] 本地T0与远程不可回滚的区别明确。
- [x] 限流等待、网络重试、授权失效、合同错误分开。
- [x] 回滚失败保留恢复备份且process非0。

## Acceptance

- [x] 24个REQ每项均有正向/负向Acceptance。
- [x] 高风险输入矩阵、16个故障注入点与机器Oracle已定义。
- [x] 55个Required Acceptance均指定目标test及Evidence合同。

## Evidence

- [x] 证据与repo/consumer/工具版本/命令/digest绑定。
- [x] BLOCKED/SKIPPED不算PASS，Release非PASS则退出非0。
- [ ] RC2目标测试实际执行证据已齐备（本稿不声称已有）。

## Plan Readiness

- [x] 新增设计默认值与来源事实已分开，部署变量缺失行为有定义。
- [x] 文档引用与完整性可由结构检查器核对。
- [x] 需求提出方完成第 0.4 节语义评审，并要求五处门禁与该节对齐。
- [x] 人工审批记录已形成且PRD状态改为APPROVED_FOR_PLAN。

# 32. PRD 禁止写法

归属：REQ-GOV-001。执行者不得把本稿明确条件降级为口号。

| 不接受的描述 | 本项目应使用的可判定合同 |
|---|---|
| 接口运行正常 | SOURCE返回批准样本ID；Operation只在真实腾讯结果后SUCCEEDED |
| 自动处理冲突 | 同key不同hash返回409且0业务mutation |
| 确保权限安全 | 未授权员工通过REST/MCP/下载/job/事件六入口均不得取得正文 |
| 测试通过即可 | 55项Required证据齐备，真实消费者7项PASS，Gate exit0 |
| 失败完整恢复 | 本地范围等于T0；远程不确定记录UNKNOWN，不伪造远程回滚 |
| 配置完成就是接入成功 | 配置/身份/Webhook/STS/真实资源探测分别有状态和证据 |

# 33. 推荐 ID 体系

本稿采用`REQ-领域-序号`；Invariant为`INV-同slug-01`；每个规范子项为`REQ-ID.N1/N2/N3`；Acceptance为`A-同slug-01/02`，真实消费方为`A-LIVE-001…007`；Test为`TEST-A-ID`，Evidence为`EVID-A-ID`，故障注入为`FI-01…FI-16`。

引用ID不能重用给另一个含义；需求拆分保留原ID并标迁移关系。所有ID以本稿实体定义为准，不允许使用不存在的REQ进行提交或计划关联。

# 34. PRD 最小完整结构

本稿采用附件的完整第0—36章，而不是删减为短模板。其最小结构映射如下：

| 最小结构 | 本稿位置 |
|---|---|
| Meta/Goal/Background | 第1–3章 |
| Scope/Boundary/Terminology | 第4–6章 |
| State/SOT/State Machine/Schema | 第7–9章 |
| Requirements | 第10章 |
| Side Effects/Ownership/Hash | 第11–13章 |
| Transaction/Failure/Conflict | 第14–15、23章 |
| Migration/External/Security/Observability | 第16–19章 |
| Acceptance/Edge/Negative | 第20–22章 |
| Evidence/Release/Golden/Traceability | 第24–27章 |
| Plan/Review/Quality/DoD | 第28–36章 |

# 35. Definition of Done

归属：REQ-GOV-001、REQ-EVID-001。分为两个完成定义，禁止混淆。

**PRD可以进入计划的条件：**所有24个REQ的N项有唯一语义，37章完整，SOT、side effect、ownership、hash、事务、冲突、失败、AC/Oracle/Evidence引用完整，语义评审通过；批准记录绑定PRD文件digest，状态为APPROVED_FOR_PLAN。本稿已满足该状态条件。真实腾讯联调证据仍然缺失，不能把本状态写成发布 PASS。

**RC2达到对接目的的条件：**真正的内部应用后端可完成凭据兑换、按登记策略创建、源查询、录制/完整转写/指定纪要、授权下载、事件消费；指定智能体可经MCP调用同一服务；旧合同不被静默破坏；55项Required Acceptance含真实消费者7项全部PASS，证据可验证。

内部系统无需持有腾讯密钥，无需为普通业务访问Meeting Portal，无需把自身审批、任务或OA流程搬进网关。没有任何程序性“已实现”标记能代替以上结果。

# 36. 最终原则

**Meeting负责连接腾讯并交付受控接口，内部系统负责自己的业务。**

接入配置、签名、OAuth、STS、事件差异、分页限流和错误恢复由网关承担；调用方获得清晰的资源与状态，而不是一套必须先学习的会议平台工作流。

任何新增功能以是否帮助内部系统完成“创建、查询、取结果、下载、接事件”为判断依据。范围外业务不因为已有Portal页面而重新进入本Release。

同一会议能力只有一个业务Owner、同一权限执行路径和可追溯来源。一次受理不等于一次成功，内容事件不等于内容可交付，合成测试不等于真实联调，REVIEW不等于APPROVED_FOR_PLAN。

## 36.1 CODE依据索引

所有CODE引用基于第1章ZIP digest锁定，路径为包内相对路径。行号可能随RC2开发变化，基线symbol与digest优先。

| ID | 代码/材料 | 支持的结论 |
|---|---|---|
| CODE-C01 | app/api/business.py:18–41 | 旧目录读取、创建prepare和内容读取入口 |
| CODE-C02 | app/services/operation_service.py::_parameters/prepare/confirm | SERVICE拒绝、AWAITING_CONFIRMATION与Portal确认基线 |
| CODE-C03 | app/services/meeting_service.py::list/get/recordings | 本地目录及录制读取；非上游源查询 |
| CODE-C04 | app/services/auth_service.py::exchange/client_credentials | 既有下游凭据模式 |
| CODE-C05 | app/services/event_service.py::process_inbox/_schedule_personal/publish/deliver | 既有事件、扫描和outbox，可复用而非从零 |
| CODE-C06 | app/services/rate_service.py::acquire、app/core/config.py | 默认节流及配置；不是本轮性能实测 |
| CODE-C07 | app/integrations/tencent_meeting/client.py::OPERATIONS/call | 已有腾讯白名单和适配路径 |
| CODE-C08 | app/mcp/tools.py::TOOL_DEFINITIONS | 原7工具及Portal确认描述 |
| CODE-C09 | app/schemas/requests.py、app/schemas/control.py | 继承字段与原默认值的冻结基线 |
| CODE-C10 | docs/PROVENANCE.md、pyproject.toml | 仓库SHA、包依赖和此前验证边界 |
| CODE-C11 | nodeskclaw-meeting-rc2-integration-checklist.md、meeting_review/offline-probe-results.json | 先前离线故障记录，不是本轮新执行Evidence |

## 36.2 文档交付说明

本稿交付的是已批准进入计划的需求合同。不存在虚构的腾讯实测、本轮产品代码修改、GitHub 提交或业务部署。状态为 APPROVED_FOR_PLAN 只允许随后编制计划，不表示联调或发布已经通过。后续范围变更需更新 PRD 版本与相应 REQ/AC，状态回到 REVIEW 并重新计算 `prd_digest`。

