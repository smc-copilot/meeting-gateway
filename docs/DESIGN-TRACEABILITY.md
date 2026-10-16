# Design 实现追踪与差异

本文把 design 的 34 条验收要求映射到源码与现有证据。**源码已提供不等于所有现场验收通过**。下表“本地通过”仅指对应的本地测试；腾讯、Backend、PostgreSQL、客户端和部署环境的边界另行说明。

路径前缀省略的服务文件在 `app/`，测试在 `tests/`。确切测试统计以 `reports/FINAL-VERIFICATION.md` 为准。

| 要求 | 能力 | 实现位置 | 本地测试或检查 | 证据边界 |
|---|---|---|---|---|
| AT-01 | 应用类型 / 字段隔离 | schemas/requests.py; services/admin_service.py | test_admin_connections.py | 本地模型与加密检查；真实应用凭证待联调 |
| AT-02 | 每员工独立 OAuth 连接 | services/connection_service.py | test_admin_connections.py | 状态、所有者和存储隔离测试；真实双用户授权待联调 |
| AT-03 | STS 提前 / 乱序关联 | services/connection_service.py; event_service.py | test_sts_early_callback_waits_for_request_and_newer_wins | 本地通过；腾讯回调现场验证待执行 |
| AT-04 | 官方工具与网关验证分离 | services/diagnostic_service.py; Portal diagnostics | test_portal_bootstrap_and_no_implicit_read | 逻辑已实现；官方工具不是本地测试项 |
| AT-05 | 企业录制分窗、分页、限流 | services/sync_service.py; rate_service.py | test_corp_sync_window_and_dedup_upsert; test_corporate_rate_limiter_is_shared_in_database | 本地模拟通过；多实例 PostgreSQL / 真实数据待验证 |
| AT-06 | 完整转写、失败不发布 | services/content_service.py; Tencent mapper.py | test_transcript_full_inclusive_pagination; test_partial_or_stuck_transcript_never_published | 本地通过；真实长会议核对待执行 |
| AT-07 | 元宝正文与空 todo | Tencent mapper.py; services/content_service.py | test_normalize_minutes_preserves_empty_todo | 本地通过；不伪造原生下载 |
| AT-08 | 同步覆盖状态 | services/meeting_service.py; sync_service.py | test_visible_before_pagination_and_resource_nonleak | 响应带真实本地覆盖；生产历史完整度待导入 |
| AT-09 | 标准 MCP | mcp/server.py; mcp/tools.py | test_mcp_protocol_handshake_list_and_wrong_audience; test_mcp_sdk_accepts_wire_contract | HTTP 协议本地通过；SDK 检查跳过，真实客户端授权待验证 |
| AT-10 | 双通道原生接口 | Tencent client.py; services/connection_service.py | test_tencent_transport.py | 传输与隔离模拟通过；真实两个应用各自验收 |
| AT-11 | 查看不隐含正文/下载 | services/permission_service.py | test_read_does_not_imply_content_or_download | 本地通过 |
| AT-12 | 跨组织 / 主体替换 | core/types.py; permission_service.py; resources APIs | test_tenant_cannot_be_overridden; test_visible_before_pagination_and_resource_nonleak | 本地通过；部署级渗透仍需执行 |
| AT-13 | 客户端不能冒充员工 | services/auth_service.py; Backend addon | test_exchange_requires_both_client_and_employee; test_client_credentials_not_employee_impersonation | 本地通过；真实 Backend 联调待执行 |
| AT-14 | 令牌类别与受众 | services/auth_service.py | test_raw_upstream_or_backend_token_rejected; test_refresh_cannot_change_audience | 本地通过 |
| AT-15 | OAuth state / 企业 / 回跳 | services/connection_service.py; auth_service.py | test_oauth_foreign_corporation_not_activated; test_oauth_state_single_use_and_confirmation_bound_to_owner | 本地通过；腾讯回跳待联调 |
| AT-16 | 智能体 / 代创建身份 | services/operation_service.py; permission_service.py | test_agent_extra_scope_cannot_expand_member; test_oauth_invitee_identity_does_not_delegate_operator_authority | 本地通过；邀请人不变成操作者 |
| AT-17 | 撤权后工具调用 | services/auth_service.py; mcp/server.py | test_client_disable_revokes_existing_access; test_rest_metadata_only_mcp_equivalent_denial | 撤权和共享权限逻辑通过；现场 agent 会话复验 |
| AT-18 | 下载撤权、续传 | services/download_service.py | test_download_rechecks_revocation_and_expiry; test_streaming.py | 许可与流边界测试；真实长流定时撤权待验证 |
| AT-19 | 禁止跨通道借权 | Tencent client.py; connection_service.py | test_upstream_errors_sanitized_no_redirect_or_fallback | 本地通过 |
| AT-20 | 私有来源不合并权限 | models/resources.py; permission_service.py | test_oauth_private_source_is_not_org_shared; test_cache_read_still_checks_current_origin_and_action | 本地通过；同上游会议可显示为不同本地资源 |
| AT-21 | 伪回调 / SSRF | Tencent webhook.py; storage/safe_http.py | test_forged_callback_not_persisted; test_download_url_validation_blocks_ssrf | 本地规则通过；实际 DNS / 网络出口测试待执行 |
| AT-22 | 管理不隐含正文 | services/admin_service.py; permission_service.py | test_bootstrap_once_and_no_implicit_content; test_superadmin_is_not_content_permission | 本地通过 |
| AT-23 | 拒绝 agent 自确认 | api/portal.py; services/operation_service.py | test_admin_token_cannot_confirm_and_unknown_fields_forbidden; test_confirm_only_trusted_owner_then_execute_once | 本地通过 |
| AT-24 | 身份服务失效关闭 | Backend client.py; API deps; callbacks/router.py | test_member_disable_and_identity_outage_fail_closed | 本地通过；真实停用/改密/组织禁用联调待执行 |
| AT-25 | 脱敏 / 安全契约 | services/audit_service.py; core/errors.py; contracts | test_error_payload_never_echoes_input_secret; test_outbox_same_transaction_and_no_title_or_body | 本地检查通过；最终反向代理日志配置由部署负责 |
| AT-26 | 创建幂等 / 并发 | services/operation_service.py; core/database.py | test_creation_prepare_is_cross_protocol_idempotent | 本地幂等通过；20 并发 PostgreSQL 验收未执行 |
| AT-27 | 超时结果不确定 | services/operation_service.py; job_service.py | test_upstream_timeout_unknown_never_retry; test_creation_transport_timeout_is_uncertain | 本地通过；真实进程故障注入待执行 |
| AT-28 | 事件去重 / 租约 | services/event_service.py; job_service.py; worker.py | test_webhook_exact_challenge_and_replay_dedup; test_job_lease_fencing_and_retry_after | 本地通过；真实多进程停启待验证 |
| AT-29 | 落库失败不伪 ACK | callbacks/router.py; services/event_service.py | 回调先事务提交；错误经统一处理 | 实现顺序已核对；数据库真实故障注入待执行 |
| AT-30 | OAuth 刷新并发协调 | services/connection_service.py; core/database.py | test_postgres_independent_connections_lock_and_claim | 代码有数据库协调；该 PostgreSQL 门槛跳过，刷新压力未执行 |
| AT-31 | 内部通知重试 / 去重 | services/event_service.py; examples/webhook_consumer.py | test_outbox_same_transaction_and_no_title_or_body; test_event_example_verifies_exact_bytes_and_commits_idempotently | 本地通过；实际接收端网络重试待联调 |
| AT-32 | 大文件流与上游地址 | services/download_service.py; storage/safe_http.py | test_streaming.py; test_stream_quota_and_single_range_validation | 流式本地通过；真实媒体 URL / 带宽 / 断点待验证 |
| AT-33 | 保留与来源撤销 | services/maintenance_service.py; permission_service.py | test_maintenance_expires_private_bytes_and_confirmation; test_disabling_ingestion_client_invalidates_cached_origin | 本地通过；生产存储备份恢复/删除待验证 |
| AT-34 | 迁移、回滚、旧系统 | alembic; scripts/integrate.py; integration/ | test_initial_migration_can_upgrade_and_repeat; test_installer.py | SQLite 重复迁移 / 安装器通过；真实 PostgreSQL、Portal 和旧系统回归待执行 |

## 实施时明确的选择

- 来源安全优先：两条 connection 分别保存相同腾讯会议，不自动跨通道合并成更大权限；可产生两条本地资源记录。
- `SELF_CREATED` 仅接受网关已确认创建的证据；历史主持人不当作创建者。历史资源使用经批准的明确范围。
- 管理权限首版是组织级 MANAGE，不把某会议的资源管理权提升为全组织管理。业务读取 / 下载仍支持会议和资产范围。
- 列表和正文使用本地资源与当前访问规则；原生数据未同步时返回未就绪/覆盖情况，不返回伪完整结果。
- 首版只提供加密文件系统存储及共享卷部署；没有未实现的 S3 配置。
- 不把元宝正文自行转换后标为腾讯原生导出；没有对应原生地址则禁止该下载。
- Portal 表单采用实际 DTO 的 Schema 驱动，而不是独立复制验证规则；已提供 Vue 组件源码，完整构建待目标仓库执行。
- 已实现 MCP 线协议而非简单重命名 REST；SDK 测试是可选外部门槛，当前缺依赖时跳过。
- 主体状态从 Backend 实时核验，数据访问权限在 Meeting；已有 Backend 全能 Token 不直接成为 MCP Token。

## 不在首版范围

公开应用市场、腾讯客户端会中 JSAPI 页面、周期会议、修改/取消、ASR、OA、文档对比翻译、RAG。此前 design 的未来扩展边界保留，不将其标记为本包已实现。

## 尚未跑过的质量门槛

Python 3.12 目标环境回归、联网解析依赖锁、Ruff、真实 PostgreSQL 跨进程压力、完整 SDK 授权会话、Vue 模板/类型检查及 Vite 构建、Docker/Kubernetes、目标 monorepo 原功能回归、腾讯真实两通道。相应脚本和 CI 配置已提供，但 CI 配置本身不是执行通过证据。
