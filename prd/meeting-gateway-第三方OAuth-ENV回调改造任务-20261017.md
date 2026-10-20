# meeting-gateway｜腾讯会议第三方 OAuth 与 Webhook 固定回调改造任务

- 状态：待实施（尚未修改目标仓库，尚未在真实服务器测试）
- 核对仓库：`smc-copilot/meeting-gateway`
- 核对 `master`：`53db51000548e01d318135b0c9869e7ee15bef73`
- 本阶段唯一腾讯通道：第三方应用 OAuth 2.0
- 应用主体：腾讯企业 ID `210022394`；腾讯应用 ID / OAuth `sdk_id` `33510141629`
- 服务器根目录：`/data/projects/meeting-gateway`；联调工具：`/data/projects/meeting-integration-kit`
- 公开入口：`https://copilot.superic.com:9999`

## 1. 硬性边界

1. 腾讯应用配置以网关 `.env` 为唯一事实源；不得从 Backend 读取应用配置，不得依赖 `/api/v1/admin/applications` 完成首次配置。
2. Backend 身份只允许本项目已有的 `POST /api/v1/auth/account-login` 调用；不得调用 `meeting-context`、`principals/resolve`、`principals/search`、`auth/me`、`auth/refresh` 或 Backend 健康探针。
3. 腾讯 OAuth 的 `sdk_id` 是第三方应用 ID，必须用于发起授权和交换 `access_token`；**不使用企业自建应用 SecretId/SecretKey、AK/SK、STS**。
4. 公开回调路径固定为：
   - `GET /callbacks/tencent/oauth/33510141629`
   - `GET /callbacks/tencent/events/33510141629`
   - `POST /callbacks/tencent/events/33510141629`
5. 保留数据库中的 Application UUID、Connection UUID、事务和权限关系；外部路径的 `33510141629` 作为 **sdk_id 的公开别名**，在服务端严格映射为本地 ENV 应用。不得将数字强行写为 UUID 主键，也不得放开为任意应用路由。
6. 回调为腾讯公网异步请求，不应依赖 Backend 用户登录和会话。事件消息先验签解密、持久化/去重、快速响应，再由 Worker 处理。
7. 所有 OAuth 和 Webhook 凭据都不得出现在源码、日志、追踪、报告、响应或命令行历史中。截图中已经暴露过的凭据须轮换。
8. 禁止创建/取消会议、全企业同步、音视频下载、AK/SK 和 MCP 测试；本轮只验证 OAuth 授权与只读会议数据获取。

## 2. 目标环境配置（示例，密钥在本机私密设置）

```dotenv
ENVIRONMENT=production
PUBLIC_BASE_URL=https://copilot.superic.com:9999
ALLOWED_HOSTS=["copilot.superic.com","localhost","127.0.0.1"]

IDENTITY_MODE=account_login
ACCOUNT_LOGIN_URL=http://192.168.102.247:4510/api/v1/auth/account-login
ACCOUNT_LOGIN_ALLOW_PRIVATE_HTTP=true
MEETING_COMPONENT_ID=meeting-gateway
MEETING_ORG_ID=<本地组织ID>
MEETING_BOOTSTRAP_ADMIN_USER_IDS=["<经批准的管理员外部用户ID>"]

TENCENT_MEETING_AUTH_MODE=oauth
TENCENT_MEETING_CORP_ID=210022394
TENCENT_MEETING_APP_ID=33510141629
TENCENT_MEETING_APP_SECRET=<轮换后的OAuth客户密钥>
TENCENT_MEETING_ALLOWED_OPEN_CORP_IDS=["<从真实OAuth返回核实并批准的open_corp_id>"]
TENCENT_MEETING_OAUTH_RETURN_URIS=[]

TENCENT_MEETING_WEBHOOK_NAME=smc-copilot-webhook
TENCENT_MEETING_WEBHOOK_EncodingAESKey=<轮换后的WebhookEncodingAESKey>
TENCENT_MEETING_WEBHOOK_Token=<轮换后的WebhookToken>
TENCENT_MEETING_WEBHOOK_URL=https://copilot.superic.com:9999/callbacks/tencent/events/33510141629

MEETING_ENABLED=true
MEETING_CREATE_ENABLED=false
MEETING_CORP_SYNC_ENABLED=false
MEETING_MEDIA_DOWNLOAD_ENABLED=false
MEETING_MCP_ENABLED=false
```

配置 Schema 须同时兼容规范大写下划线名 `TENCENT_MEETING_WEBHOOK_ENCODING_AES_KEY` / `TENCENT_MEETING_WEBHOOK_TOKEN` 和这里约定的混合名称，建议使用 Pydantic `AliasChoices`；不要依赖 `case_sensitive=False` 去匹配是否存在下划线的差异。生产校验：App ID 非空、必须为 OAuth、Webhook AES 解码得 32 字节、Webhook URL 与 `PUBLIC_BASE_URL`+固定路径严格一致。启动检查只输出配置是否完整和 URL，**不输出 Secret、AESKey、Token**。

## 3. 源码变更点

| 路径 | 当前行为 | 必须实现 |
|---|---|---|
| `app/core/config.py` | 已有 OAuth 应用 ENV 字段，尚无 Webhook ENV 字段 | 新增 Webhook 4 字段、严格 URL/格式校验、SecretStr 与别名支持 |
| `app/services/identity_service.py` | 首次 `ensure_deployment` 才 `_project_tencent`；已有应用不会自动更新 OAuth 凭据；ENV 应用 receiver 是随机 UUID | 引入启动时/显式命令运行的 ENV 应用幂等 reconcile；存在应用时匹配 owner、corp_id、sdk_id、org_id，按实际变化加密轮换 OAUTH_APP/WEBHOOK 凭据。已有数据库不得丢弃 UUID、连接/交易状态或密文存储密钥 |
| `app/callbacks/router.py` | OAuth 路由将 `{application_id}` 当数据库 UUID 传给服务；事件路由将 `{receiver_id}` 当随机 receiver | 对外只接受配置的数字 App ID 作为 ENV 回调别名，通过严格映射解析为实际 Application.id / receiver_id；通过原有服务执行，不复制 OAuth 或验签逻辑。旧非 ENV 路由的兼容行为需单独测试 |
| `app/services/connection_service.py` | 发起授权 URL 使用 `app.id` 生成 redirect_uri | ENV 应用生成 `PUBLIC_BASE_URL/callbacks/tencent/oauth/<sdk_id>`；内部 transaction、token、Connection 仍使用 Application UUID。`state` 必须一次性校验与消费 |
| `app/services/event_service.py` | 用数据库 receiver_id 找应用、读取加密 `WEBHOOK` 凭证，GET 验签解密，POST 收件箱去重 | 通过公开数字别名间接得到正确 receiver；只有签名有效时处理；POST 先持久化再回 200；重复事件不重复入库；不把凭证与正文写入日志 |
| `app/cli.py`, `.env.example`, `docs/tencent-setup.md` | 示例未包含新 Webhook 字段 | 更新 ENV 合同、启动自检说明、回调地址及安全警告 |
| `deploy/nginx.conf.example` | 443 示例；回调有位置规则 | 给出可合入现有 9999 HTTPS server 的两个 location，不占用已有页面；回调访问日志不得包含 `$request` / `$request_uri` / `$args` / 原始 Query |
| `tests/integration/test_events.py` + OAuth/identity tests | 以随机内部 ID 测回调 | 增加固定数字路径回调、状态校验、错误/重试和 ENV 更新测试 |

## 4. 回调合同

### OAuth

授权链接遵循官方格式：

```text
https://meeting.tencent.com/marketplace/authorize.html?corp_id=<企业ID>&sdk_id=<应用ID>&redirect_uri=<URLENCODE(固定OAuth回调)>&state=<随机不可猜值>
```

只有授权通过浏览器重定向后，URL 才带 `auth_code` 和 `state`。服务端核对已创建的 `state` 事务、公开 ID 与 ENV 应用匹配、事务未使用且未过期后，再通过以下 **腾讯官方** 接口交换令牌：

```text
POST https://meeting.tencent.com/wemeet-webapi/v2/oauth2/oauth/access_token
Content-Type: application/json
{"sdk_id":"33510141629","secret":"<仅从加密凭据读取>","auth_code":"<真实一次性授权码>"}
```

响应为 HTTP 200 且 JSON `code=0`、存在 `data.access_token` / `data.open_id` 等字段才算令牌交换成功。HTTP 200 + `code=10` 是失败。临时授权码有效期 5 分钟、一次性使用；`string required` 不是授权码，禁止反复尝试。OAuth Token 只保存在服务端加密存储。

OAuth 回调可以返回受控无令牌结果页；浏览器端只展示安全的 `connection_id` 和状态，Token 不进入 URL。

### Event webhook

腾讯保存回调时：

```text
GET /callbacks/tencent/events/33510141629?check_str=<URL编码密文>
timestamp: ...
nonce: ...
signature: ...
```

服务端按官方算法验证签名，AES-CBC 解密 `check_str`，**在 3 秒内仅返回解密后的原始明文**（无引号、无换行）。

真实事件时：

```text
POST /callbacks/tencent/events/33510141629
Content-Type: application/json
Headers: timestamp / nonce / signature
Body: {"data":"<加密事件密文>"}
```

验签解密、事件去重和持久化成功后在 5 秒内返回 **HTTP 200** 且正文严格为 `successfully received callback`。事件后续通过 Worker 处理；失败或伪造请求不得返回成功确认。

## 5. Nginx 联调要点

保留现有 HTTPS 9999 server；新增精确回调 location（检查现有 location 的优先级），示例：

```nginx
# 适用于现有 listen 9999 ssl 的 server 块内部
location = /callbacks/tencent/oauth/33510141629 {
    proxy_pass http://127.0.0.1:4522;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_read_timeout 10s;
}
location = /callbacks/tencent/events/33510141629 {
    proxy_pass http://127.0.0.1:4522;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_read_timeout 10s;
}
```

这段不是完整 Nginx 配置：需沿用现场证书和原站点其它 locations。**对这两个 location 的日志必须另用只记录 `$uri`（无 query）的安全格式或关闭访问日志**；GET OAuth 的 query 中含 `auth_code`、`state`，不得落盘。反向代理应保留原始 query/header/body，不能 301/302 到无 query 的页面，也不能增加需要内部用户认证的 Nginx 访问限制。其余业务 API 不因此对公网匿名开放。

## 6. 测试顺序与验收

1. **代码门禁**：固定执行 commit SHA、完整现有测试；搜索确认无 Backend 旧接口调用；新 ENV Schema 有测试、缺值启动失败。
2. **配置门禁**：仅在白名单机器保存凭据，验证容器 `.env` 生效、`PUBLIC_BASE_URL` 与腾讯回调 URL 完全一致；禁止读取密钥写入报告。
3. **服务门禁**：PostgreSQL 迁移成功、API/Worker 正常、Nginx `nginx -t` 通过。外部回调路径直连无合法参数返回受控 4xx 是正常现象，不能用 `curl -I` 判断 OAuth 成功。
4. **Webhook**：在腾讯事件订阅后台提交 URL，由腾讯发起签名 GET 验证。显示保存成功且本地 `webhook_verified_at` 更新才算通过；事件触发后收件箱出现唯一事件。
5. **OAuth**：在网关端以测试用户合法会话发起授权，浏览器跳转腾讯并同意，回来后完成令牌交换与员工确认；`open_corp_id` 必须与单独批准的允许列表一致。
6. **数据读取**：OAuth `user_info`、用户历史会议或录制（限所授权应用与账号实际访问范围）→ 真实目标会议 → 完整转写与腾讯原生纪要。`202`、空列表和连接 `ACTIVE` 不算已取到数据。
7. **权限测试**：其它员工凭自己的会话不应读取该授权用户的私有会议；访问伪造事件/错误签名应失败；`state` 重放/`auth_code` 重放必须失败。
8. **结果报告**：记录操作时间、执行 SHA、入站/出站 IP、HTTP 状态、腾讯业务码、私有证据路径、回调成功及资源匹配结论；明确 PASSED/FAILED/BLOCKED/NOT_RUN，不回显密钥。

### 特别说明

- **第三方 OAuth 仍使用 sdk_id**：它是应用 ID，不是企业自建应用的 SecretId；不能因为不用 AK/SK 就去掉 `sdk_id`。
- `TENCENT_MEETING_CORP_ID` 是创建应用的企业 ID；授权用户返回的 `open_corp_id` 是独立字段，不应默认视为相等。需要实际记录并批准。
- Backend 的账号登录只验证一次账号/密码并返回内部身份；**不能靠解码其 JWT 就声称已完成验签**。员工会议权限由网关本地会话和 ACL 校验。
- 不能用 OAuth 查询要求 AK/SK 的企业级录制接口；本阶段只读属于已授权用户及应用能访问的数据。
- 官方 OAuth 调试截图中的 `code=10` 由无效 `auth_code` 引起，不能当成服务端鉴权配置成功。

## 7. Hermes 实施指令

> 读取 `/data/projects/meeting-gateway` 的当前代码与 Git 状态，核对本任务文档后在独立开发分支实施第 3 节增量改造。先补失败测试，再完成固定 SDKID 回调别名、ENV Webhook 凭证加密装载、启动幂等同步以及 OAuth redirect。运行完整测试并保存真实证据，不替换旧数据库卷和 KEYRING，不重置其他业务站点的 9999 入口。测试通过后生成 patch/commit 给代码审查；批准部署前不自动修改腾讯生产后台，不用截图泄露的旧凭证进行联调。本轮验收仅做用户 OAuth 与已授权会议数据只读提取。缺实际密钥时报告 BLOCKED，不生成假回调、假令牌或模拟报告来替代真实联调。
