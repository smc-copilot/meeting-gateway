from pathlib import Path
import importlib.util
import subprocess
import os
import sys

ROOT=Path(__file__).resolve().parents[2]


def test_initial_migration_can_upgrade_and_repeat(tmp_path):
    assert (ROOT/'alembic.ini').is_file()
    env={**os.environ,'MIGRATION_DATABASE_URL':'sqlite:///'+str(tmp_path/'migration.db')}
    for _ in range(2):
        result=subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=ROOT,env=env,capture_output=True,text=True)
        assert result.returncode==0,result.stderr
    from sqlalchemy import create_engine,inspect
    from app.models.base import Base
    engine = create_engine(env['MIGRATION_DATABASE_URL'])
    try:
        assert set(Base.metadata.tables) <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_monorepo_integration_files_are_real_modules():
    for name in ('integration/backend/app/api/meeting_identity.py','integration/portal/src/features/meeting/routes.ts',
                 'integration/portal/src/features/meeting/MeetingConsole.vue','scripts/integrate.py','README.md','deploy/compose.yaml'):
        assert (ROOT/name).is_file(),name
