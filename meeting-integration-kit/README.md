# 腾讯会议网关联调操作包

适用代码：`smc-copilot/meeting-gateway`（以当前仓库提交为准）。

**内部系统业务对接请优先阅读《内部系统对接联调说明.md》。**  
主链路为：免鉴权起腾讯会议授权（仅 `return_to` 白名单）→ 扫码回调 → `/oauth/sessions`（需 client）换 `mt_` → 取会议数据。  
`POST /api/v1/auth/account-login` 与 `POST /api/v1/auth/exchange` 已停用（410）。《部署与生态联调操作手册.md》中仍写这两步的段落已过时。

执行顺序见《部署与生态联调操作手册.md》（部署/基础设施）与《内部系统对接联调说明.md》（业务对接）。本包是仓库外的操作工具，不修改网关服务源码，不包含任何真实凭证。

- `tools/call.py`：按接口合同发送请求、保存私有原始响应、输出脱敏回执。
- `tools/poll.py`：轮询既有作业或操作，不重复提交。
- `tools/store.py`、`tools/exchange_form.py`：保存凭证；`exchange_form.py` 仅适用于已退役的 exchange，新联调请用 `/oauth/sessions`。
- `tools/read_content.py`：轮询生成状态，遍历转写分页并核对版本。
- `tools/download.py`：读取网关下载许可，流式保存文件。
- `tools/event_receiver.py`：内部系统签名事件接收样例，只监听回环地址。
- `tools/report.py`：按授权、只读、生态、MCP范围生成报告，缺证据退出非零。

工具使用 Python 标准库，建议 Python 3.12+。网关本身仍按仓库依赖安装。

原始响应保存在 `private/`，可能含应用密钥、内部客户端密钥、访问令牌或会议正文，不可上传报告系统。`evidence/` 保存脱敏回执。报告不能替代人工核对真实腾讯样本。

源码依赖、API调用和接收事件均在目标环境执行；本包交付时仅执行本地脚本测试，没有执行真实腾讯联调。

操作工具不重试创建、应用登记或授权写请求。read_content.py 的 fetch=ensure 可能在网关排入后台作业；“只读”指不创建/修改腾讯会议，不代表网关数据库和缓存不发生写入。
