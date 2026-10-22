3. 如果人员资料还需要补查成员详情、部门信息等，由 **AnythingLLM 后端继续调用对应查询接口并加工**，不要求 Gateway 代为拼接。
4. 取得的参会人员写入 AnythingLLM 本地参会人员表，使用本地会议 ID 关联到会议。
5. 原始接口有分页时，由 AnythingLLM 后端处理分页；人员数据更新不得无限追加成重复名单。
6. 会议与人员处理完成后，将该会议的 `query_status` 更新为 `ready`；失败时标记 `failed` 并记录原因，不长期停留 pending，也不把错误显示成零人参会。

部门、职位、企业内部身份无法从原始接口可靠取得时保存 null，展示未知；不按姓名、邮箱或其他文本猜测。

### 2.3 从本地数据组装页面响应

上两步完成后，由 AnythingLLM 后端读取 **本地会议列表 + 本地参会人员关联数据**，组装表格和人员弹框需要的复杂结构，再提供给前端。

- 前端不直接调用 Gateway，也不负责逐条补查和拼接腾讯原始数据。
- `participants` 等页面数组由 AnythingLLM 后端组装，不要求 Gateway 在 meeting-queries 中新增增强数组。
- 未完成或失败的查询需带明确状态；已有数据与本次更新失败不能混淆。
- 人员为空、资料未知和查询失败是不同情况，不能都变成空数组后显示“无参会人员”。

## 3. AnythingLLM 本地数据要求

以下只定义本次需要的业务数据，不制定数据库迁移方案。

| 本地会议数据 | 要求 |
| --- | --- |
| 本地会议 ID | 用于人员关联及现有会议编辑页 |
| 会议号 | 字符串，会议写入唯一判据 |
| 腾讯会议 ID | 保留原始标识，用于调用后续腾讯查询接口；不是本地唯一判据 |
| 会议议题、开始/结束时间 | 由 AnythingLLM 映射原始字段 |
| query_status | `pending / ready / failed`，表示本次会议和人员数据查询进度 |
| 查询错误说明 | 失败时可追踪，不伪装成成功空结果 |
| 导入状态及内容/摘要关联 | 沿用本地实际入库结果；查询落库不能自动标为已导入 |

| 本地参会人员数据 | 要求 |
| --- | --- |
| 本地会议关联 ID | 指向对应本地会议，不能关联错行 |
| 原始人员标识 | 原始接口提供时保留，供关联及避免重复使用 |
| 用户昵称、入会昵称 | 分开保存，由后端组合展示 |
| 部门、职位 | 可为 null |
| 是否企业内部人员 | true / false / null，未知不当作否 |

**查询状态与导入状态必须分开**：

- `pending` 只表示正在查询/补齐本地会议和人员数据，不表示会议内容正在导入。
- 查询元数据已经落库，不表示会议内容与摘要已经导入。
- 本地“已导入”仍要求会议内容与摘要均实际入库，不能用腾讯会议进行/结束状态代替。
- 内容与摘要的获取、加工及本地保存由 AnythingLLM 完成；Gateway 只返回相应腾讯查询的原始数据，不负责写入 AnythingLLM 或生成本地导入状态。

## 4. Meeting Gateway 当前可用的腾讯会议查询接口清单

以下为 **Gateway 已实现、可供 AnythingLLM 调用** 的查询类接口（鉴权：Meeting Bearer，`MEMBER` + 相应 `meeting.*` 权限；参会/用户基础信息/录制缓存路径网关侧仅 **OAuth 连接**；Q2/R1/R2 上游另走 env AK/SK，见各行说明）。  
字段细节另见 `docs/participants-oauth-mapping.md`、`docs/record-files-oauth-mapping.md`。Gateway **不**为页面组装 DTO，**不**写入 AnythingLLM。

### 4.1 会议列表与人员（对应当初 Q1～Q5）

| 编号 | 状态 | Gateway 路径 | 腾讯上游 | 说明 |
| --- | --- | --- | --- | --- |
| Q1 | **可用** | `POST /api/v1/meeting-queries` | `USER_WINDOW` → `GET /v1/history/meetings/{userid}`；`MEETING_ID` → `GET /v1/meetings/{meeting_id}` | 同步返回会议投影，**不嵌套参会人员**。`CORP_WINDOW` 拒绝（403）。`RECORDINGS` / `USER_RECORDINGS` 走异步 job（202）。 |
| Q2 | **可用** | `GET /api/v1/connections/{connection_ref}/meetings/{meeting_id}/participants` | [42701 获取参会成员明细](https://cloud.tencent.com/document/product/1095/42701) `GET /v1/meetings/{meeting_id}/participants`（env AK/SK，无 STS） | `meeting_id` 为腾讯源会议 ID（与 Q1 的 `meeting_id` 一致）。网关侧仍要求本人 OAuth 连接；上游用 env AK/SK，`userid` 由 open_id→企业 userid 映射。本地缓存优先；未命中则网关翻页拉全量后全成全败落库再返回。Query：`pos`/`size`（对本地全集分页）。响应含 `open_id`、`join_name`、`is_enterprise_user` 等，**无** `profile`。 |
| Q3 | **可用（并入 Q1）** | 同上 `POST /api/v1/meeting-queries`，`selection=MEETING_ID` | `GET /v1/meetings/{meeting_id}` | Q1 投影已含 `meeting_code` / `subject` / `start_at` / `end_at` / `state`；history 行若缺会议号则以上游返回为准，**不再**为人员去补查。另有本地目录 `GET /api/v1/meetings/{local_id}`（catalogue UUID，非腾讯 ID）。 |
| Q4 | **部分可用** | `POST /api/v1/oauth-users/sync` | [67432 获取用户基本信息](https://cloud.tencent.com/document/product/1095/67432) `GET /v1/users/info/basic`（需 `VIEW_USER_BASIC_INFO`） | Body：`connection_ref` + `open_ids`（去重，上限 50）。可落库：`username`、`open_corp_id`、`open_corp_name`、`status`、`avatar_url`。**无**部门、职位；企业内部身份不以本接口为准。不支持 OAuth 的 [93435 用户详情](https://cloud.tencent.com/document/product/1095/93435)，Gateway **不调用**。与 Q2 解耦，不在参会列表隐式 sync。 |
| Q5 | **不可用** | — | — | 无部门/组织详情 Gateway 接口；部门名称无法从 Q2/Q4 可靠取得时保存 null。 |

#### Q1 请求与投影字段

- 请求要点：`selection`、`connection_ref`；`USER_WINDOW` 另需 `target_member_id`（须为本人）、`start_at`/`end_at`；`MEETING_ID` 另需 `meeting_id`。
- 同步 `items[]` 投影：`meeting_id`、`subject`、`meeting_code`、`start_at`、`end_at`、`state`、`connection_ref`。
- **已删除**（勿再依赖）：`participants` / `participant_count` / `participants_status` / `participants_reason`。

#### Q2 / Q4 人员字段能力

| 业务字段 | Q2（42701 参会） | Q4（67432 basic） |
| --- | --- | --- |
| 原始人员标识 | `open_id` / `userid` / `ms_open_id` | `open_id`（入参） |
| 入会昵称 | `join_name`（自 Base64 `user_name`） | — |
| 用户昵称 | — | `username` |
| 部门 / 职位 | 无（null） | 无（null） |
| 企业内部人员 | `is_enterprise_user`（非布尔则 null） | 无可靠字段 |

### 4.2 录制列表与录制详情（新建业务接口，OAuth）

与下方 catalogue 导入路径（`GET /api/v1/meetings/{local_id}/recordings`、Q6/Q7）**并存、互不替代**。细节见 `docs/record-files-oauth-mapping.md`。

| 编号 | 状态 | HTTP | Gateway 路径 | 腾讯上游 |
| --- | --- | --- | --- | --- |
| R1 | **可用** | `GET` | `/api/v1/connections/{connection_ref}/meetings/{meeting_id}/record-files` | [51189 查询会议录制列表](https://cloud.tencent.com/document/product/1095/51189) `GET /v1/records` |
| R2 | **可用** | `GET` | `/api/v1/connections/{connection_ref}/record-files/{record_file_id}` | [51180 查询单个录制详情](https://cloud.tencent.com/document/product/1095/51180) `GET /v1/addresses/{record_file_id}` |

#### R1 录制列表（本地缓存）

- **路径参数**：`connection_ref`（本人 OAuth 连接）；`meeting_id`（**必填**，腾讯源会议 ID，与 Q1 一致）。调用方只传 `meeting_id`，不传时间窗。
- **Query**：`pos`（默认 0）、`size`（默认 20，最大 100）——对本地已缓存全集分页。
- **行为**：本地快照命中则读本地；未命中时网关用 **`.env` 企业 AK/SK** 调 51189（`operator_id=TENCENT_MEETING_APP_OPERATOR_ID`、`operator_id_type=1`；`userid` 由 open_id→userid 映射表解析，缺失则先 `POST /v1/users/open-id-to-userid`，body.`sdkid=TENCENT_MEETING_APP_ID`），并**默认**赋时间窗 `end_time=now`、`start_time=now-31天`，分页收集全部 `record_files`，按 `record_file_id` 去重后**单事务全成全败**落库，再返回本地数据。本轮无强制刷新。缺企业 AK/SK env 时返回可操作错误，不回退 OAuth。
- **鉴权**：业务入口本人 OAuth + `meeting.read`（拒绝以 AK/SK connection 调本接口）；上游腾讯侧为企业 AK/SK。
- **响应 `data` 要点**：
  - `meeting_id`、`source`（`cache` \| `fetched`）、`record_file_count`、`total_count`
  - 可选：`meeting_code`、`subject`
  - 分页：`pos`、`size`、`has_remaining`、`next_pos`
  - `record_files[]`（`record_file_id` 统一 string）：`record_start_time`、`record_end_time`、`record_size`、`sharing_state`、`sharing_url`、`required_same_corp`、`required_participant`、`password`、`sharing_expire`、`allow_download`

#### R2 录制详情（透传，不落库）

- **路径参数**：`connection_ref`；`record_file_id`（来自 R1 的 `record_files[].record_file_id`）。
- **行为**：用 **`.env` 企业 AK/SK** 调腾讯 51180（`operator_id=TENCENT_MEETING_APP_OPERATOR_ID`、`operator_id_type=1`），请求头携带部署级 **STS-Token**（`env_sts.current_token()`）；将上游 JSON **原样**放入 envelope `data`；不裁剪、不落库、不缓存（下载链约 5 分钟失效）。无 STS 时触发 refresh，仍无则 `STS_NOT_READY`；缺企业 AK/SK env 则 `UPSTREAM_CREDENTIAL_INVALID`，不回退 OAuth。
- **鉴权**：业务入口本人 OAuth + `meeting.read`（拒绝以 AK/SK connection 调本接口）；上游腾讯侧为企业 AK/SK + STS-Token。
- **响应 `data`**：腾讯原文（含 `view_address`、`download_address`、`meeting_summary` / `ai_meeting_transcripts` / 各类 `ai_*_minutes` 等，以上游实际返回为准）。

### 4.3 导入内容与摘要（对应当初 Q6～Q7，catalogue 路径）

不在会议/人员查询时自动拉取；导入动作按需调用。通常先有本地 catalogue 会议与录音（可通过 `meeting-queries` 的 `RECORDINGS` 或 `GET /api/v1/meetings/{id}/recordings` 等路径入库）。

| 编号 | 状态 | Gateway 路径 | 腾讯上游 | 说明 |
| --- | --- | --- | --- | --- |
| Q6 | **可用** | `GET /api/v1/recordings/{recording_id}/transcript` | 转写详情 `GET /v1/records/transcripts/details` | `recording_id` 为 Gateway 本地录音 ID。`fetch=ensure\|cache`；未就绪可能 202（job）或 409。段落分页：`limit`/`cursor`。 |
| Q7 | **可用** | `GET /api/v1/recordings/{recording_id}/minutes` | 智能纪要 `GET /v1/smart/minutes/{record_file_id}` | 同上本地 `recording_id`；`fetch=ensure\|cache`。 |

相关辅助（非 Q 编号，导入链路常用）：

| Gateway 路径 | 作用 |
| --- | --- |
| `GET /api/v1/meetings/{meeting_id}/recordings` | 本地会议下的录音列表；`fetch=ensure` 可触发上游拉取 job |
| `GET /api/v1/jobs/{job_id}` | 查询异步 job（含 RECORDINGS / 内容拉取） |
| `POST /api/v1/assets/{asset_id}/download-tickets` + `GET /api/v1/downloads/{ticket}` | 已入库 asset 的受控下载 |

### 4.4 能力结论（替代原「待确认回执」）

| 编号 | 结论 |
| --- | --- |
| Q1 | 可用；会议投影已含会议号等字段；**不含**人员 |
| Q2 | 可用；路径见上；仅 OAuth；本地缓存语义见 mapping 文档 |
| Q3 | 不单独开路径；用 Q1 `MEETING_ID` |
| Q4 | 仅用户基本信息可用；部门/职位不可用；93435 不可用 |
| Q5 | 不可用 |
| R1 | 可用；按腾讯源 `meeting_id` 缓存 `record_files`；只传 meeting_id；上游企业 AK/SK + open_id→userid |
| R2 | 可用；按 `record_file_id` 透传 51180 原文，不缓存；上游企业 AK/SK + STS-Token |
| Q6 / Q7 | 可用；依赖本地 `recording_id`，非腾讯会议 ID 直查 |

AnythingLLM 应按上表做本地字段映射与调用编排：Q1 落会议 → Q2 落参会 → 按需 Q4 补昵称 → 需要录制清单时调 R1 → 取播放/下载/转写链时调 R2 → catalogue 导入仍可用 Q6/Q7。部门/职位保持 null，展示「未知」/ `--`。

## 5. 页面小优化保持不变

| 顺序 | 表头 | 显示要求 |
| --- | --- | --- |
| 1 | 会议时间 | 北京时间 `YYYY-MM-DD HH:mm`，例如 `2026-10-19 16:12` |
| 2 | 会议议题 | 本地会议议题 |
| 3 | 会议号 | 本地保存的腾讯会议号，不用腾讯会议 ID 代替 |
| 4 | 参会人员 | 点击弹框，展示后端由本地关联数据组装的人员列表 |
| 5 | 导入状态 | 未导入、导入中、已导入；与 query_status 分开 |
| 6 | 操作 | 最右侧固定 100px |

人员弹框列为：**用户昵称（入会昵称）｜部门｜职位｜是否为企业内部人员**。部门、职位未知显示 `--`；企业身份未知显示「未知」。

操作规则：未导入显示可点击「导入」；导入中显示禁用「导入」；内容与摘要均已导入时显示「查看」，进入现有 `/meetings/:id` 本地会议编辑页。

## 6. 验收口径

- [ ] Gateway 只返回腾讯原始接口数据，没有为本页面增强或聚合返回结构。
- [ ] AnythingLLM 发起查询后有本地 pending 记录；清单返回后先按会议号保存 pending 会议，再逐条查询人员。
- [ ] 同一会议号重复查询只更新，不重复插入；不以腾讯会议 ID 代替会议号判重。
- [ ] 人员由 AnythingLLM 调用接口取得并写入本地表，正确关联本地会议。
- [ ] 两步完成后，页面数据由 AnythingLLM 后端从本地会议和人员数据拼接，前端不补查 Gateway。
- [ ] 成功、查询中、失败和确实无人参会可区分；刷新查询不覆盖已导入的内容、摘要或状态。
- [ ] 六列表格、时间格式、100px 操作列、人员弹框及三种导入按钮行为符合要求。
- [ ] Q1～Q7、R1/R2 以 §4 已确认清单为准：可用项按表调用；Q5 与 Q4 部门/职位不可用时保存 null，不猜测；录制清单用 R1、单文件详情用 R2，勿与 catalogue 的 local `recording_id` 路径混用。