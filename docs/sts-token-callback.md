# 企业自建应用 STS Token 回调

腾讯会议「数据敏感」类接口要求请求头携带 `STS-Token`。meeting-gateway 按部署级 env 企业自建应用接收并存储该 Token，供服务内 `env_sts.current_token()` 读取。当前消费方：R2 录制详情上游 `GET /v1/addresses/{record_file_id}`（见 [`record-files-oauth-mapping.md`](record-files-oauth-mapping.md)）。

## 企管后台配置

1. 打开腾讯会议企管后台 → 自建应用 → 事件订阅 → **添加事件订阅**。
2. 填写名称与 URL，URL 必须为：

```text
https://<PUBLIC_BASE_URL>/callbacks/tencent/app/events
```

URL 支持四级域名，且需全局唯一未被占用。

3. 保存后添加事件：事件类型选 **公共事件** → 勾选 **STS Token 生成**。
4. 将页面生成的 Token、EncodingAESKey 写入网关 `.env`：

```bash
TENCENT_MEETING_APP_WEBHOOK_TOKEN=...
TENCENT_MEETING_APP_WEBHOOK_ENCODING_KEY=...
```

5. 出站触发仍使用企业应用 AK/SK（与 R1 相同）：

```bash
TENCENT_MEETING_CORP_ID=...
TENCENT_MEETING_APP_SECRET_ID=...
TENCENT_MEETING_APP_SECRET_KEY=...
TENCENT_MEETING_APP_SDK_ID=...
TENCENT_MEETING_APP_OPERATOR_ID=...   # 超管/管理员 userid
TENCENT_MEETING_STS_VALID_HOURS=24    # 仅允许 6 / 12 / 24
TENCENT_MEETING_STS_REFRESH_MARGIN_SECONDS=3600
```

参考文档：[企业自建应用票据（STS Token 生成）](https://cloud.tencent.com/document/product/1095/127650)。

## 运行时行为

- Worker 每约 60 秒 housekeeping 调用 `env_sts.refresh_due()`。
- 无有效 ACTIVE token（距过期不足 margin）且无 10 分钟内 WAITING 时，调用 `POST /v1/app/sts-token`，落库 WAITING。
- 腾讯推送 `common.sts-token` 到 `/callbacks/tencent/app/events`，验签解密后按 `req_id` 幂等置 ACTIVE。
- 其他事件类型返回 200 但不落库，避免腾讯重推。
- GET 同路径带 `check_str` 用于事件订阅 URL 校验（challenge）。

## nginx

需放行该路径到 uvicorn（示例见 `deploy/nginx.conf.example`）：

```nginx
location = /callbacks/tencent/app/events {
    access_log /var/log/nginx/meeting-callback.log meeting_callback;
    proxy_pass http://127.0.0.1:4522;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_read_timeout 10s;
}
```

前缀 `location /callbacks/tencent/` 已覆盖时可不加精确 location，但建议显式声明以便独立 access_log。

## 故障排查

| 现象 | 原因 |
|---|---|
| GET/POST 回调 404 | 未配置 `TENCENT_MEETING_APP_WEBHOOK_TOKEN` / `ENCODING_KEY`，或 EncodingAESKey 非法 |
| 回调 401 | Token / EncodingAESKey 与企管后台不一致，或签名头缺失 |
| worker 从不触发 sts_request | 缺企业 AK/SK 五元组，或 webhook 凭证未配齐 |
| `current_token()` 返回 None | 尚无 ACTIVE，或 token 已过期（含 30 秒安全余量） |
