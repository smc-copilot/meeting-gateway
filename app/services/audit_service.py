"""Whitelisted, content-free audit events. Never store arbitrary HTTP requests."""
from app.models import AuditLog
from app.core.security import digest


def record(session, principal, action: str, *, resource_id=None, decision="ALLOW", reason=None, details=None):
    allowed = {"connection_id", "application_id", "operation_id", "job_id", "policy_version", "old_hash", "new_hash",
               "credential_fingerprint", "upstream_code", "bytes", "status", "event_id", "change_reason_hash", "grant_id"}
    safe = {key: value for key, value in (details or {}).items() if key in allowed and isinstance(value, (str, int, float, bool, type(None)))}
    session.add(AuditLog(org_id=principal.org_id, actor_type=principal.actor_type, subject_id=principal.subject_id,
        client_id=principal.client_id if principal.client_id != "portal" else None, agent_id=principal.agent_id,
        action=action, resource_id=resource_id, decision=decision, reason=reason,
        trace_id=principal.trace_id or "internal", details=safe))
