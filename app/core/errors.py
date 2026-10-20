"""Stable error contract. Never include upstream messages or validation input values.

Numeric codes are frozen. Append new reasons at the end; do not renumber existing ones.
"""
from typing import Any

_MESSAGES = {
    "AUTH_REQUIRED": "需要有效的访问凭据", "TOKEN_INVALID": "访问凭据无效或已过期",
    "AUDIENCE_MISMATCH": "访问凭据不适用于当前接口", "IDENTITY_UNBOUND": "尚未绑定腾讯会议身份",
    "IDENTITY_SERVICE_UNAVAILABLE": "暂时无法核验员工身份", "MEMBER_INACTIVE": "员工账号不可用",
    "RESOURCE_NOT_ACCESSIBLE": "资源不存在或当前无权访问", "PERMISSION_DENIED": "当前操作未获授权",
    "SOURCE_GRANT_INVALID": "资料来源授权无效", "UPSTREAM_REAUTH_REQUIRED": "需要重新授权腾讯会议",
    "UPSTREAM_PERMISSION_DENIED": "腾讯会议未允许本次访问", "UPSTREAM_CAPABILITY_UNAVAILABLE": "该连接不支持此能力，请检查授权范围",
    "CONTENT_NOT_READY": "完整内容尚未就绪", "SOURCE_REMOVED": "原始资源已不可用",
    "DOWNLOAD_NOT_ALLOWED": "资料不允许下载", "CONFIRMATION_REQUIRED": "需要员工确认",
    "IDEMPOTENCY_CONFLICT": "幂等键对应了不同的请求", "OUTCOME_UNKNOWN": "上游操作结果待核对",
    "RATE_LIMITED": "调用频率已达到限制", "UPSTREAM_UNAVAILABLE": "腾讯会议暂时不可用",
    "UPSTREAM_CONTRACT_ERROR": "上游返回未符合已验证的数据契约", "CONTENT_CHANGED": "获取期间内容发生变化",
    "INVALID_REQUEST": "请求参数不符合契约", "CURSOR_INVALID": "分页游标无效或已过期",
    "STATE_INVALID": "授权事务无效或已过期", "IDENTITY_CONFLICT": "外部身份绑定冲突",
    "FEATURE_DISABLED": "该功能尚未启用", "OPERATION_EXPIRED": "操作确认已过期",
    "AUTHORIZATION_CHANGED": "授权已变化，需要重新准备操作", "SSRF_BLOCKED": "目标地址不在许可范围内",
    "INTERNAL_ERROR": "服务内部错误，请提供追踪标识", "DOWNLOAD_EXPIRED": "下载许可已过期",
    "REFRESH_REUSE": "检测到刷新凭据重复使用，令牌族已撤销", "STS_NOT_READY": "临时访问票据尚未就绪",
    "RETENTION_UNCONFIRMED": "组织尚未确认数据保存策略", "CONFLICT": "资源状态冲突",
    "AUTO_RECORD_DISABLED": "自动云录制尚未启用，请联系管理员开启创建录制策略",
    "CONTENT_ABSENT": "上游没有可读取的内容",
    "UPSTREAM_CLOCK_SKEW": "请求时间与腾讯会议服务器偏差过大，请检查时钟与签名时间",
    "UPSTREAM_CREDENTIAL_INVALID": "企业应用凭证未通过校验，请检查 SecretId 与 SecretKey",
    "UPSTREAM_DAILY_QUOTA": "已达到腾讯会议当日调用额度，请明天再试，不要按分钟反复重试",
    "IDENTITY_CONFIG_INVALID": "身份配置无效",
    "LEGACY_IDENTITY_CONFIG_FORBIDDEN": "仍保留已废弃的身份桥配置",
    "IDENTITY_NAMESPACE_MISMATCH": "组件或组织与已绑定的数据库不一致",
    "IDENTITY_EGRESS_FORBIDDEN": "禁止访问账号登录以外的身份接口",
    "ACCOUNT_LOGIN_REJECTED": "账号或密码不正确",
    "ACCOUNT_LOGIN_UNAVAILABLE": "账号登录暂时不可用",
    "ACCOUNT_LOGIN_CONTRACT_ERROR": "账号登录响应不符合约定",
    "ACCOUNT_ORG_MISMATCH": "登录组织与本网关配置不一致",
    "ACCOUNT_ORG_REQUIRED": "账号尚未完成组织初始化",
    "ACCOUNT_PASSWORD_CHANGE_REQUIRED": "需要先在原系统修改密码",
    "IDENTITY_REAUTH_REQUIRED": "需要重新登录",
    "LOCAL_MEMBER_DISABLED": "该成员已在网关本地停用",
    "LOCAL_MEMBER_NOT_ENROLLED": "该员工还没有完成本地登录",
    "IDENTITY_MIGRATION_REQUIRED": "旧成员引用缺少明确映射",
    "IDENTITY_MAPPING_CONFLICT": "旧成员与外部用户不是一一对应",
    "ADMIN_REAUTH_REQUIRED": "管理操作需要一次新的登录",
    "LAST_ADMIN_DISABLE_FORBIDDEN": "不能停用最后一个有效管理员",
    "IDENTITY_MODE_CHANGED": "登录模式已变化，请重新登录",
    "ROLE_UNRECOGNIZED": "组织角色无法识别，已按普通成员处理",
    "ACCOUNT_LOGIN_DISABLED": "账号登录接口已停用，请通过腾讯会议授权扫码完成接入",
    "AUTH_EXCHANGE_DISABLED": "令牌交换接口已停用，请使用 OAuth 授权完成后的会话换票接口",
}
ERROR_CODES = {
    "AUDIENCE_MISMATCH": 710001, "AUTHORIZATION_CHANGED": 710002, "AUTH_REQUIRED": 710003,
    "CONFIRMATION_REQUIRED": 710004, "CONFLICT": 710005, "CONTENT_CHANGED": 710006,
    "CONTENT_NOT_READY": 710007, "CURSOR_INVALID": 710008, "DOWNLOAD_EXPIRED": 710009,
    "DOWNLOAD_NOT_ALLOWED": 710010, "FEATURE_DISABLED": 710011, "IDEMPOTENCY_CONFLICT": 710012,
    "IDENTITY_CONFLICT": 710013, "IDENTITY_SERVICE_UNAVAILABLE": 710014, "IDENTITY_UNBOUND": 710015,
    "INTERNAL_ERROR": 710016, "INVALID_REQUEST": 710017, "MEMBER_INACTIVE": 710018,
    "OPERATION_EXPIRED": 710019, "OUTCOME_UNKNOWN": 710020, "PERMISSION_DENIED": 710021,
    "RATE_LIMITED": 710022, "REFRESH_REUSE": 710023, "RESOURCE_NOT_ACCESSIBLE": 710024,
    "RETENTION_UNCONFIRMED": 710025, "SOURCE_GRANT_INVALID": 710026, "SOURCE_REMOVED": 710027,
    "SSRF_BLOCKED": 710028, "STATE_INVALID": 710029, "STS_NOT_READY": 710030,
    "TOKEN_INVALID": 710031, "UPSTREAM_CAPABILITY_UNAVAILABLE": 710032, "UPSTREAM_CONTRACT_ERROR": 710033,
    "UPSTREAM_PERMISSION_DENIED": 710034, "UPSTREAM_REAUTH_REQUIRED": 710035, "UPSTREAM_UNAVAILABLE": 710036,
    "AUTO_RECORD_DISABLED": 710037, "CONTENT_ABSENT": 710038, "UPSTREAM_CLOCK_SKEW": 710039,
    "UPSTREAM_CREDENTIAL_INVALID": 710040, "UPSTREAM_DAILY_QUOTA": 710041,
    "IDENTITY_CONFIG_INVALID": 710042, "LEGACY_IDENTITY_CONFIG_FORBIDDEN": 710043,
    "IDENTITY_NAMESPACE_MISMATCH": 710044, "IDENTITY_EGRESS_FORBIDDEN": 710045,
    "ACCOUNT_LOGIN_REJECTED": 710046, "ACCOUNT_LOGIN_UNAVAILABLE": 710047,
    "ACCOUNT_LOGIN_CONTRACT_ERROR": 710048, "ACCOUNT_ORG_MISMATCH": 710049,
    "ACCOUNT_ORG_REQUIRED": 710050, "ACCOUNT_PASSWORD_CHANGE_REQUIRED": 710051,
    "IDENTITY_REAUTH_REQUIRED": 710052, "LOCAL_MEMBER_DISABLED": 710053,
    "LOCAL_MEMBER_NOT_ENROLLED": 710054, "IDENTITY_MIGRATION_REQUIRED": 710055,
    "IDENTITY_MAPPING_CONFLICT": 710056, "ADMIN_REAUTH_REQUIRED": 710057,
    "LAST_ADMIN_DISABLE_FORBIDDEN": 710058, "IDENTITY_MODE_CHANGED": 710059,
    "ROLE_UNRECOGNIZED": 710063,
    "ACCOUNT_LOGIN_DISABLED": 710064, "AUTH_EXCHANGE_DISABLED": 710065,
}


class MeetingError(Exception):
    def __init__(self, reason: str, status: int = 400, *, data: Any = None, retry_after: int | None = None, budgeted: bool = True):
        self.reason, self.status, self.data, self.retry_after, self.budgeted = reason, status, data, retry_after, budgeted
        super().__init__(reason)

    def payload(self, trace_id: str) -> dict:
        return {"code": self.status, "error_code": ERROR_CODES.get(self.reason, 719999),
                "message_key": "errors.meeting." + self.reason.lower(),
                "message": _MESSAGES.get(self.reason, _MESSAGES["INTERNAL_ERROR"]),
                "reason": self.reason, "data": self.data, "trace_id": trace_id}


class UpstreamError(MeetingError):
    def __init__(self, reason: str, *, upstream_code: str = "", uncertain: bool = False, retry_after=None, budgeted: bool = True):
        super().__init__(reason, 502, retry_after=retry_after, budgeted=budgeted)
        self.upstream_code = upstream_code[:64]
        self.uncertain = uncertain
