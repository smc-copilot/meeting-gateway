# nodeskclaw-meeting

腾讯会议双通道应用接入、REST API 和 MCP 权限网关。版本：**1.0.0rc1（交付候选源码，尚未完成生产环境验收）**。

对应仓库：`loudon84/nodeskclaw`，核对基线：`83edfb0d97f07920deb8bb9ce44a91e3e32cc3af`。本包是独立子项目及增量集成模块，**不是整个 nodeskclaw 仓库的副本**。Backend / Portal 的原有源码仍来自你们仓库。

## 已提供的源码

| 模块 | 内容 |
|---|---|
| 独立服务 | FastAPI 工厂、SQLAlchemy asyncio、独立 PostgreSQL、Alembic、API / Worker 进程、健康检查、受控指标 |
| 腾讯接入 | AK/SK 按实际发送字节签名、OAuth 用户连接、加密凭证、异步 STS 回调关联、应用隔离、原生接口适配 |
| 员工权限 | Backend 实时身份核验、显式权限、资源范围、采集来源、拒绝优先、员工停用和委托撤销 |
| 对内 REST | 会议列表、录制、完整转写、纪要、同步作业、受控下载、创建准备与操作查询 |
| 自建 MCP | 2025-11-25 Streamable HTTP 无状态 JSON 模式、7 个工具、逐调用鉴权；不依赖腾讯官方 MCP 灰度 |
| 对内授权 | 客户端登记、令牌交换、授权码 + PKCE S256、刷新轮换 / 重放撤销、严格 REST / MCP 受众隔离 |
| 创建闭环 | 一次性会议、不可变参数摘要、真实员工确认、单次上游执行、结果不确定时禁止盲目重试 |
| 同步闭环 | PostgreSQL 作业租约、事件收件箱 / 发件箱、分页游标、企业批准采集、个人 OAuth 补偿、重试和权限复核 |
| 文件出口 | 绑定主体的下载许可、单 Range 续传、逐连接 DNS 检查、无重定向、限并发 / 限速 / 日配额、流式传输 |
| 管理界面 | Vue 3 Portal 模块：应用、连接、员工权限、内部应用、智能体、会议、确认、诊断、审计 |
| 增量集成 | Backend 身份接口模块；支持预览、冲突检测、幂等安装、回滚的安装脚本 |

## 快速接入现有仓库

先将本目录放到仓库根目录，与 `nodeskclaw-backend` / `nodeskclaw-knowledge` / `nodeskclaw-task` 并列。

```bash
# 在 nodeskclaw 仓库根目录执行；首先只预览变更。
python nodeskclaw-meeting/scripts/integrate.py --repo . --dry-run
python nodeskclaw-meeting/scripts/integrate.py --repo . --apply
```

脚本仅添加 Meeting 模块和两个路由接入点，不会把整个 Backend、Portal 替换掉。安装状态存放在仓库根 `.meeting-integration-state.json`，原文件备份在 `.meeting-integration-backup/`。请将这两项加入本地 `.git/info/exclude`，不要提交备份。已被人工修改的已安装文件会阻止覆盖 / 回滚；先检查差异。

回滚代码接入（不回滚数据库、不删除会议数据）：

```bash
python nodeskclaw-meeting/scripts/integrate.py --repo . --rollback
```

### 1. 准备环境

Python 3.12 或 3.13、PostgreSQL、uv；Portal 使用现有 Vue 3 / Vite 环境。生产数据库必须使用 `postgresql+asyncpg://`。SQLite 仅为明确选择的离线单进程测试辅助，不是生产部署选项。

```bash
cd nodeskclaw-meeting
uv sync --group dev
uv run python -m app.cli generate-env \
  --public-base-url https://meeting-gateway.your-company.example \
  --portal-base-url https://console.your-company.example \
  --backend-url http://nodeskclaw-backend:8000 \
  --database-host postgres
```

域名示例必须替换为真实值。命令创建权限为 `0600` 的 `.env`，拒绝覆盖已有文件，不把随机密钥打印到终端。`KEYRING_JSON` 是网关数据库和正文存储的加密密钥，必须备份。丢失旧密钥将无法解密既有数据。不要上传 `.env`、截图中的真实凭证或生产 Token。

本次生成环境不能访问依赖注册表，**没有伪造 `uv.lock`**。首次联网部署运行 `scripts/lock_dependencies.sh`，审核实际解析和格式检查结果，再把生成的 lock 文件纳入你们仓库。Dockerfile 当前也需要联网安装依赖；正式发布前应固定镜像摘要和依赖锁。

### 2. 配置 Backend 身份桥

身份只走账号登录。网关 `POST /api/v1/auth/account-login` 把账号和密码转发到配置里的唯一登录地址，然后签发本地 `ms_` 会话。不要配置 `NODESKCLAW_BACKEND_URL` 或 `BACKEND_SERVICE_TOKEN`。不要调用 `meeting-context`、`principals/resolve`、`principals/search`。

### 3. 启动数据库、迁移、API 和 Worker

```bash
# 从 nodeskclaw-meeting 目录执行。
docker compose --env-file .env -f deploy/compose.yaml up --build -d
```

API 仅绑定主机 `127.0.0.1:4522`，在 `deploy/nginx.conf.example` 的 HTTPS 443 入口反向代理。容器内访问另一套 Backend 必须配置真实可达的 Docker 网络地址；另一进程在宿主机运行时，可配置 `http://host.docker.internal:4510`。不要把容器自身的 localhost 当作宿主机。

不用 Docker 的开发启动方式：

```bash
# DATABASE_URL 指向实际 PostgreSQL；本地可将 STORAGE_PATH 改为 storage/private。
uv run alembic upgrade head
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 4522 --no-access-log
# 另一个终端启动，使用同一数据库和私有文件目录。
uv run python -m app.worker
```

迁移是独立步骤，不会在每个 API 副本启动时抢占执行。Kubernetes 示例见 `deploy/kubernetes.yaml.example`：先完成 migration Job，API 和 Worker 共用私有 RWX 存储。本实现提供本地 / 共享文件系统的加密存储适配，不提供未经实现的 S3 配置开关。

### 4. 启用 Portal 页面

在 **Portal** 的环境中配置并重新构建：

```text
VITE_MEETING_ENABLED=true
VITE_MEETING_GATEWAY_URL=https://meeting-gateway.your-company.example
```

登录现有 Portal 后访问 `/meeting/overview`。接入模块自带 Meeting 内部导航，但不会侵入修改整个 Portal 的主导航。需要主导航入口时，在你们现有菜单配置里加入 `/meeting`。

以组织管理员初始化本组织的 Meeting 管理权限，然后按顺序登记应用、绑定员工身份、创建连接、批准采集保留策略、给具体员工和内部应用授权。初始化管理权限**不包含正文读取、下载、创建等业务权限**。

## 腾讯两种应用怎么配置

详细清单见 `docs/tencent-setup.md`。当前 OAuth 应用与新增企业级自建应用分别登记，不能混用客户密钥、SecretId / SecretKey、回调 Token 和 STS-Token。

企业自建应用先绑定真实腾讯企业用户 ID，再建立企业连接。配置 Webhook URL 并通过腾讯校验，申请 STS，接收 `common.sts-token`。只有真实只读探测成功后才记录相应能力；“应用已保存”不等于腾讯接入已验证。

OAuth 应用配置实际 `open_corp_id` 白名单。员工完成腾讯授权后，还需要在 `/meeting/connections` 确认其账号绑定；不匹配企业的连接保持 `CORP_MISMATCH`。OAuth Token 按员工和应用分别保存，私有来源不自动共享给全组织。邀请参会人使用同应用、同企业、已核验的身份映射，不授予其操作者身份。

公网授权回调、Webhook、H5 可信域名和 API 公网出口 IP 是不同配置。官方开发者调试工具由腾讯控制台手工开启；网关诊断页面只测试明确的能力，不提供任意腾讯 URL 代签。官方工具会对真实资源发出请求，它绕过网关，不能代替内部权限验收。

敏感功能默认关闭；完成联调后明确设置并重启 API / Worker：

```text
MEETING_MCP_ENABLED=true
MEETING_CREATE_ENABLED=true
MEETING_CORP_SYNC_ENABLED=true
MEETING_MEDIA_DOWNLOAD_ENABLED=true
```

最后一项只在确有媒体下载需求且已配置 `MEDIA_ALLOWED_HOSTS` 时开启。允许域名必须来自已核验的腾讯原生下载地址，不允许通配符或任意目标。内网通知同理使用确切域名，私网地址还需显式配置允许网段。

## 内部调用与权限

对内 REST 前缀为 `/api/v1`；MCP 为 `/mcp`。**它们是不同 OAuth resource / token audience**。员工应用通过 `/api/v1/auth/exchange` 提交客户端凭据和真实 Backend 员工令牌，不能只传一个 employee_id 冒充员工。无人值守服务使用独立的 client credentials，并且必须另有明确的采集批准；采集身份不自动获得员工阅读能力。

普通业务权限：`meeting.read`、`meeting.content.read`、`meeting.content.download`、`meeting.create.self`、`meeting.create.on_behalf`、`meeting.sync.manage`。动作授权与资源范围、来源有效性、客户端范围、智能体委托取交集；任何拒绝规则优先。

`SELF_CREATED` 只信任网关已确认的创建结果，不能把上游主持人字段当作创建者证明。对于客户端历史会议，在未获得可核实创建者证据前使用明确的资源 / 企业批准授权，不猜测创建者。

管理面需要单独的组织级 MANAGE 授权；资源 ACL 不自动提供动作权限。不支持把一个仅限指定会议的管理授权升级为全组织管理。禁用客户端、授权或连接后，既有缓存和下载请求仍要重新检查当前权限。

REST 调用示例：`examples/rest_client.py`；MCP 只读工具示例：`examples/mcp_client.py`；内部事件签名校验：`examples/webhook_consumer.py`。

## 创建会议与不确定结果

```text
准备请求（Idempotency-Key）
→ AWAITING_CONFIRMATION
→ 员工通过 Backend 真实登录在 Portal 核对参数
→ QUEUED → EXECUTING
→ SUCCEEDED / FAILED / OUTCOME_UNKNOWN
```

参数变化后原确认失效。智能体没有自确认工具。相同请求键不会盲目产生新的创建请求。腾讯超时或进程在写入后中断时，操作转为 `OUTCOME_UNKNOWN`；只能经人工核对关联一场参数一致且另行同步验证的会议，或关闭为未核实。关闭未核实不表示腾讯一定没有创建成功。

## 数据与下载边界

原生转写必须完整遍历段落游标；内容不完整、游标停滞或格式不符时，不写成 READY。读取带版本信息，不能悄悄跨版本拼接。原生纪要保留模型 / 类型；空的 `todo` 不自动视为失败。

下载只使用腾讯实际提供的对应原生导出地址，不把本地转换文件伪装成腾讯原件。**默认元宝纪要没有本项目已核验的原生导出字段时，返回 DOWNLOAD_NOT_ALLOWED；不会偷换成其他模型的纪要。**

Portal 大文件下载使用 File System Access API 流式写盘，不把完整视频缓存在浏览器 Blob 内存里。不支持该 API 的浏览器使用提供的 Python 流式客户端。HTTP 层支持绑定主体的单 Range 续传，令牌到期应更新令牌后以同一主体继续。服务端不能收回已经下载的字节。

本地正文加密、私有目录无静态服务；审计不记录全文或凭证。组织批准的保留天数由 Worker 执行；数据库业务删除采用软删除，正文密文到期删除。跨组织资源 ID、列表、缓存、下载、事件订阅都要经过当前授权检查。

## 契约、测试和已知验证边界

```bash
uv run pytest
uv run pytest --cov=app --cov-report=term-missing
uv run python scripts/export_contracts.py
uv run python -m compileall -q app integration/backend
```

`contracts/` 包含从真实注册路由和 DTO 导出的 OpenAPI、前端接口包、MCP 工具 Schema 和内部事件 Schema。接口契约不等于已经完成腾讯真实调用。

本地执行结果与确切数量见 `reports/FINAL-VERIFICATION.md`。测试使用真实 FastAPI / httpx ASGI / SQLAlchemy / 加密与适配器代码，并模拟腾讯与 Backend 返回；不含真实员工、生产凭据或真实创建行为。真实 PostgreSQL 并发测试与 MCP SDK 合同测试在环境不足时明确跳过，不能把 SQLite 的结果当作 PostgreSQL 多进程已通过。

`.github/workflows/ci.yml` 提供联网 CI：Python 3.12、PostgreSQL、SDK 合同和基线 Portal 构建。它在本次环境没有执行。monorepo 使用时需复制到仓库根 `.github/workflows/meeting.yml`。正式发布前必须通过真实 PostgreSQL、Portal 构建、真实 Backend 集成、两类腾讯应用只读/创建联调与安全评审。

### 本次交付明确不声称

不声称真实商业版接口、账号权限、创建配额、下载地址白名单已经验证；不声称 Docker 镜像、Kubernetes、PostgreSQL 多进程、Vue 类型检查、Vite 构建或 SDK 客户端全流程已在此环境通过；不包含公开应用市场上架、周期会议、取消/修改会议、腾讯客户端 JSAPI 页面、S3 存储、ASR、RAG 或 OA 业务处理。

既有项目的子系统本来就需要独立部署。本包既不包含 Backend 登录系统的替代实现，也不以返回假身份、硬编码管理员、空函数或模拟腾讯成功的方式掩盖集成依赖。

## 文件布局

```text
app/                 服务实现：API、OAuth、MCP、模型、权限、同步、下载
alembic/             自动生成并审核的初始迁移
integration/backend/ Backend 身份桥源码
integration/portal/  Vue 管理页面及模块级中英文文案
scripts/             增量安装、契约导出、依赖锁定、语法检查
contracts/           REST / 前端 / MCP / 事件契约
examples/            内部应用与智能体接入示例
deploy/              Docker、Compose、Nginx、Kubernetes；根目录含 .env.example
tests/               单元、集成、安全、协议、迁移、安装回滚测试
reports/             本地执行证据和验证边界
docs/                已批准 design、腾讯配置清单、交付说明
```

先审核和配置，再联调再投产。更多来源与实现差异见 `docs/PROVENANCE.md` 和 `docs/DESIGN-TRACEABILITY.md`。
