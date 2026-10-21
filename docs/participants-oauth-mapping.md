# OAuth 参会成员与用户基础信息

`POST /api/v1/meeting-queries` **不再**内嵌参会人员。会议投影仅含：`meeting_id` / `subject` / `meeting_code` / `start_at` / `end_at` / `state` / `connection_ref`。

人员能力拆成两条独立路径：

## 1. 参会名单（本地缓存 + 腾讯 42701）

- 接口：`GET /api/v1/connections/{connection_ref}/meetings/{meeting_id}/participants`
- 上游：[获取参会成员明细](https://cloud.tencent.com/document/product/1095/42701) — `GET /v1/meetings/{meeting_id}/participants?userid={openId}&pos=&size=`
- 行为：本地 `meeting_participant_snapshots` / `meeting_participant_rows` 命中则直接返回；未命中则服务端翻页拉全量，**单事务全成全败**落库后再返回。本轮无强制刷新。
- **不关联** `meeting_oauth_users`，响应无 `profile`。

| 腾讯字段 | 网关字段 | 说明 |
| --- | --- | --- |
| `user_name`（Base64） | `participants[].join_name` | 解码失败则为 null |
| `open_id` / `userid` / `ms_open_id` | 同名回传 + 去重键 | 优先 open_id |
| `is_enterprise_user` | `is_enterprise_user` | 非布尔则为 null |

响应另含：`source`（`cache` \| `fetched`）、本地分页 `pos` / `size` / `has_remaining` / `next_pos`、`participant_count`。

## 2. 用户基础信息（oauth-users sync）

- 接口：`POST /api/v1/oauth-users/sync`
- 上游：[获取用户基本信息](https://cloud.tencent.com/document/product/1095/67432) — `GET /v1/users/info/basic?operator_id={open_id}&operator_id_type=2`
- 落库表：`meeting_oauth_users`，活跃唯一键 `(org_id, open_id)`；`open_corp_id` 仅为字段。
- 单条失败记入结果，不整批失败。上限 50 个 open_id。
- OAuth 应用需权限点 `VIEW_USER_BASIC_INFO`。

注意：诊断用的 `oauth('user_info')`（`/wemeet-webapi/v2/oauth2/oauth/user_info`）只用于校验当前授权人，不用于参会名单。  
[93435 用户详情](https://cloud.tencent.com/document/product/1095/93435) 不支持 OAuth，本网关不调用。
