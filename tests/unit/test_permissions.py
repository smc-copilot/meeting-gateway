from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import pytest


def principal(**kwargs):
    from app.core.types import Principal
    values = dict(org_id="o1", actor_type="MEMBER", member_id="m1", client_id="c1", scopes=frozenset({"meeting.read", "meeting.content.read", "meeting.content.download", "meeting.create.self"}))
    return Principal(**(values | kwargs))


def grant(**kwargs):
    values = dict(org_id="o1", subject_type="MEMBER", subject_id="m1", effect="ALLOW", purpose="ACCESS",
                  actions=["meeting.read", "meeting.content.read", "meeting.content.download"],
                  scope_type="ORG_APPROVED", resource_ids=[], connection_ids=[], asset_types=[],
                  target_member_ids=[], expires_at=None, deleted_at=None, enabled=True)
    return SimpleNamespace(**(values | kwargs))


def resource(**kwargs):
    from app.services.permission_service import ResourceContext
    values = dict(org_id="o1", meeting_id="r1", connection_id="cn1", host_member_id="m1",
                  source_kind="ENTERPRISE_AKSK", source_owner_id=None, source_active=True, ingestion_active=True)
    return ResourceContext(**(values | kwargs))


def check(grants=None, res=None, who=None, **kwargs):
    from app.services.permission_service import evaluate
    return evaluate(who or principal(), grants if grants is not None else [grant()], res or resource(),
                    action=kwargs.pop("action", "meeting.content.read"), **kwargs)


def test_default_deny():
    assert not check(grants=[])


def test_org_approved_and_source_ingestion():
    assert check()
    assert not check(res=resource(ingestion_active=False))


def test_tenant_cannot_be_overridden():
    assert not check(res=resource(org_id="o2"))
    assert not check(grants=[grant(org_id="o2")])


def test_deny_precedes_allow():
    assert not check(grants=[grant(), grant(effect="DENY")])


def test_read_does_not_imply_content_or_download():
    assert not check(grants=[grant(actions=["meeting.read"])])
    assert not check(who=principal(scopes=frozenset({"meeting.read"})))


def test_asset_type_restriction():
    assert check(grants=[grant(asset_types=["minutes"])], asset_type="minutes")
    assert not check(grants=[grant(asset_types=["minutes"])], asset_type="transcript")


def test_expiry_and_disabled_grant():
    assert not check(grants=[grant(expires_at=datetime.now(UTC)-timedelta(seconds=1))])
    assert not check(grants=[grant(enabled=False)])


def test_self_created_and_explicit_scope():
    assert check(grants=[grant(scope_type="SELF_CREATED")])
    assert not check(grants=[grant(scope_type="SELF_CREATED")], res=resource(host_member_id="m2"))
    assert check(grants=[grant(scope_type="EXPLICIT", resource_ids=["r1"])])
    assert not check(grants=[grant(scope_type="EXPLICIT", resource_ids=["r2"])])


def test_oauth_private_source_is_not_org_shared():
    assert check(res=resource(source_kind="THIRD_PARTY_OAUTH", source_owner_id="m1", ingestion_active=False))
    assert not check(res=resource(source_kind="THIRD_PARTY_OAUTH", source_owner_id="m2"))


def test_revoked_connection_denies_cached_content():
    assert not check(res=resource(source_active=False))


def test_connection_scope_is_enforced():
    assert not check(grants=[grant(connection_ids=["cn2"])])


def test_agent_extra_scope_cannot_expand_member():
    who = principal(actor_type="AGENT", agent_id="a1", agent_grant_id="ag1")
    agent = grant(resource_ids=["r2"], scope_type="EXPLICIT")
    assert not check(who=who, agent=agent)
    assert not check(who=who, grants=[], agent=grant())
    assert not check(who=who, agent=None)
    assert check(who=who, agent=grant(resource_ids=["r1"], scope_type="EXPLICIT"))


def test_resource_acl_deny_cannot_be_bypassed():
    acl = SimpleNamespace(org_id="o1", resource_type="meeting", resource_id="r1", subject_type="MEMBER", subject_id="m1", effect="DENY", actions=["meeting.content.read"], asset_types=[], expires_at=None, deleted_at=None)
    assert not check(acls=[acl])


def test_superadmin_is_not_content_permission():
    assert not check(who=principal(is_super_admin=True), grants=[])


def test_unknown_scope_and_untrusted_participants_deny():
    assert not check(grants=[grant(scope_type="UNKNOWN")])
    assert not check(grants=[grant(scope_type="PARTICIPATED")])
    assert check(grants=[grant(scope_type="PARTICIPATED")], res=resource(participant_member_ids=("m1",)))
