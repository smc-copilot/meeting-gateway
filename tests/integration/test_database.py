import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


@pytest.mark.asyncio
async def test_database_utc_and_soft_delete_partial_unique(tmp_path):
    from app.core.database import Database
    from app.models import Application
    db = Database(f"sqlite:///{tmp_path}/db.sqlite", allow_sqlite=True)
    await db.create_schema_for_test()
    async with db.session() as s:
        row = Application(org_id="o", name="app", application_type="ENTERPRISE_AKSK", environment="test", tencent_corp_id="tc", sdk_id="sdk", data_scope="enterprise")
        s.add(row); await s.commit(); ident=row.id
    async with db.session() as s:
        row = await s.get(Application, ident)
        assert row.created_at.tzinfo is not None
        row.soft_delete(); await s.commit()
    async with db.session() as s:
        s.add(Application(org_id="o", name="new", application_type="ENTERPRISE_AKSK", environment="test", tencent_corp_id="tc", sdk_id="sdk", data_scope="enterprise"))
        await s.commit()
    await db.close()


def test_sqlite_refused_for_production():
    from app.core.database import Database
    with pytest.raises(ValueError):
        Database("sqlite://", allow_sqlite=False)
