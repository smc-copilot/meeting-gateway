# nodeskclaw-meeting v1 Implementation Plan

**Goal:** 将已确认的双通道设计实现为可下载的独立服务与 monorepo 集成源码。
**Architecture:** Python 3.12+ / FastAPI；PostgreSQL + SQLAlchemy asyncio；Backend 身份来源；Meeting 执行授权；REST / stateless Streamable HTTP MCP 共用服务。
**Spec:** `docs/design.md`（本次用户明确要求按该设计交付源码）。
**Execution:** 当前隔离目录内连续实现，不改远程仓库、不调用真实腾讯写接口。

## Global Constraints
凭证不出网关；默认拒绝；无跨通道自动重试；一次性会议创建；禁止 agent 自确认；生产使用 PostgreSQL；敏感功能默认关闭。

## Review Focus
1. 相同员工不同客户端、不同 audience 不能混用令牌或游标。
2. OAuth source、企业采集 source 不能合并出更大权限。
3. 启动后发出的 webhook 必须先落库；STS 乱序不能覆盖新票据。
4. 创建请求超时/进程退出不能盲目重建会议。
5. 刷新令牌复用、权限撤销、下载续传必须重新验证。

## Task 1 — Core and persistence
Files: app/core/{config,security,errors,database,types}.py; app/models/*.py; tests/unit/test_core.py.
Interfaces: Settings, Principal, KeyRing, Database.session()/lock(), UTC datetime; typed SQLAlchemy entities.
- [x] Write failing crypto/config/policy-shape tests; run pytest.
- [x] Implement core and relational schema; run unit tests.
- [x] Generate Alembic initial revision with CLI, review SQL, test migrations.

## Task 2 — Identity and permissions
Files: integrations/nodeskclaw_backend/client.py; services/{permission_service,admin_service,audit_service}.py.
Interfaces: BackendClient.context/resolve; PermissionService.check/list_visible; Principal from verified identity.
- [x] Pin deny-first, tenant, asset type, private-source and bootstrap tests.
- [x] Implement grants, ACL and origin enforcement; test list filtering before pagination.

## Task 3 — Downstream authorization
Files: authorization/*.py; services/auth_service.py; authorization/router.py.
Interfaces: token issue/authenticate/rotate/revoke; exact resource audience; PKCE consent transactions.
- [x] Test subject impersonation, audience, code replay, refresh reuse/revocation.
- [x] Implement private exchange, authorization-code/PKCE, client credentials and Portal consent.

## Task 4 — Tencent dual channel
Files: integrations/tencent_meeting/{signing,webhook,client,mapper}.py; services/connection_service.py.
Interfaces: provider methods accept selected connection and typed operator only.
- [x] Test actual signed bytes, OAuth headers, expiry conversion, STS correlation and typed mapping.
- [x] Implement upstream auth/refresh, callbacks, explicit capability diagnostics.

## Task 5 — Resources and synchronization
Files: services/{meeting_service,content_service,sync_service,job_service}.py; worker.py.
Interfaces: local IDs, per-connection namespaces, encrypted assets, durable paged jobs and coverage.
- [x] Test partial transcript never READY, overlapping inclusive pid pages, private origins, job recovery.
- [x] Implement ingestion and read paths, cadence compensation and durable inbox/outbox.

## Task 6 — Operations and downloads
Files: services/{operation_service,download_service}.py; storage/*.py.
Interfaces: prepare/confirm/run, idempotency; ticket-bound streaming and periodic revoke checks.
- [x] Test duplicate keys, altered request, unauthorized confirmation, unknown outcome, download SSRF.
- [x] Implement worker operations and secured streaming; retry same-connection addresses only.

## Task 7 — HTTP and MCP
Files: api/*.py; mcp/*.py; main.py; contracts/*.
Interfaces: strict REST envelope, real JSON-RPC initialize/notifications/tools, OAuth metadata.
- [x] Test REST and MCP equivalent denials, version negotiation, host/origin/body limits.
- [x] Implement endpoints; generate contracts from real code.

## Task 8 — Monorepo adapters and Portal
Files: integration/backend/*.py; integration/portal/*; scripts/integrate.py.
- [x] Test installer dry-run/idempotency/refusal to overwrite unrelated files.
- [x] Provide complete Backend addon and Portal Vue module, build/check commands and reversible install.

## Task 9 — Release evidence
Files: deploy/*; Dockerfile; README.md; docs/DESIGN-TRACEABILITY.md; reports/*.
- [x] Run available tests, compile, migration SQL checks, secret scan and archive integrity.
- [x] Record unavailable PostgreSQL/SDK/Portal build/live Tencent checks separately; never mark skipped as passed.
- [x] Package source and verification evidence; no caches, private config, binaries or upstream token values.

## 交付状态说明
源码步骤在当前隔离目录完成，真实环境门槛另列于 `reports/FINAL-VERIFICATION.md`；完成代码步骤不表示已执行 PostgreSQL、Vue、腾讯或部署验证。没有创建远程提交或 PR。
