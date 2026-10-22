# OAuth 会议录制列表缓存与详情透传

与 catalogue 路径（`GET /api/v1/meetings/{local_id}/recordings`、本地 `recording_id` 的 transcript/minutes）**并存**，互不替代。

## R1 录制列表（本地缓存 + 腾讯 51189）

- 接口：`GET /api/v1/connections/{connection_ref}/meetings/{meeting_id}/record-files`
- 上游：[查询会议录制列表](https://cloud.tencent.com/document/product/1095/51189) — `GET /v1/records`
- 入参：腾讯源 `meeting_id`（**必填**，与 meeting-queries 一致）；可选本地分页 `pos`/`size`；`start_time`/`end_time` 由网关默认赋最近 31 天，调用方不传
- 业务鉴权：本人 OAuth `connection_ref` + `meeting.read`（路径不变）
- 上游鉴权：**企业 AK/SK**（`.env`，不是 OAuth AccessToken）
  - `TENCENT_MEETING_CORP_ID` → `AppId`
  - `TENCENT_MEETING_APP_SECRET_ID` / `TENCENT_MEETING_APP_SECRET_KEY`
  - `TENCENT_MEETING_APP_SDK_ID` → 请求头 `SdkId`
  - `TENCENT_MEETING_APP_OPERATOR_ID` → 查询参数 `operator_id`（`operator_id_type=1`）
- `userid`：本地表 `meeting_oauth_userid_maps` 将 OAuth `open_id`（`connection.external_id`）映射为企业 `userid`；未命中则 AK/SK 调 `POST /v1/users/open-id-to-userid`（body.`sdkid` = `.env` `TENCENT_MEETING_APP_ID`，即当前 OAuth 第三方应用 ID；`operator_id` = `TENCENT_MEETING_APP_OPERATOR_ID`）后落库再查录制
- 行为：
  1. 本地快照命中 → 直接按本地 `record_files` 返回
  2. 未命中 → 校验企业 AK/SK env → 解析 userid → 默认时间窗 `end_time=now`、`start_time=now-31天` → 分页拉 `/v1/records?meeting_id=...&userid=...&operator_id=...&operator_id_type=1` → 按 `record_file_id` 去重后**单事务全成全败**落库，再返回本地数据
- 唯一键：`(org_id, connection_id, external_meeting_id, record_file_id)`（活跃 Partial Unique）
- `password` 等共享字段会落库并回传；**禁止**写入 audit/日志
- 本轮无强制刷新

响应要点：`meeting_id`、`source`（`cache`|`fetched`）、`record_files[]`（字段对齐腾讯 RecordFile，`record_file_id` 统一 string）。

## R2 录制详情（透传 51180，不缓存）

- 接口：`GET /api/v1/connections/{connection_ref}/record-files/{record_file_id}`
- 上游：[查询单个录制详情](https://cloud.tencent.com/document/product/1095/51180) — `GET /v1/addresses/{record_file_id}`
- Gateway **原样**返回腾讯 JSON（播放/下载地址、转写/纪要下载链等）；不落库、不裁剪
- 下载类链接约 5 分钟失效，故不做详情缓存
- 本轮仍走连接既有上游通道（未改为 env AK/SK）

两条接口业务侧均仅 **本人 OAuth 连接** + `meeting.read`。
