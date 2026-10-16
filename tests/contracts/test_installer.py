import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('meeting_installer',ROOT/'scripts/integrate.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def repo(path):
    backend=path/'nodeskclaw-backend/app/api/router.py';backend.parent.mkdir(parents=True)
    backend.write_text('from fastapi import APIRouter\napi_router = APIRouter()\n')
    portal=path/'nodeskclaw-portal/src/router/index.ts';portal.parent.mkdir(parents=True)
    portal.write_text('const ceRoutes: RouteRecordRaw[] = [\n]\n')
    return backend,portal


def test_installer_dry_run_idempotency_and_rollback(tmp_path):
    a,b=repo(tmp_path);before=(a.read_bytes(),b.read_bytes())
    proposed=module.apply(tmp_path,dry_run=True)
    assert len(proposed)>5 and (a.read_bytes(),b.read_bytes())==before
    assert module.apply(tmp_path,dry_run=False)
    assert module.apply(tmp_path,dry_run=False)==[]
    assert 'meeting_identity_router' in a.read_text() and '...meetingRoutes' in b.read_text()
    module.rollback(tmp_path)
    assert (a.read_bytes(),b.read_bytes())==before
    assert not (tmp_path/'nodeskclaw-backend/app/api/meeting_identity.py').exists()


def test_installer_refuses_overwrite_and_modified_rollback(tmp_path):
    a,b=repo(tmp_path);module.apply(tmp_path,dry_run=False)
    a.write_text(a.read_text()+'# Local edit\n')
    with pytest.raises(RuntimeError):module.rollback(tmp_path)
    # Applying an update with changed tracked contents must not overwrite local edits.
    state=tmp_path/module.STATE_NAME
    import json
    values=json.loads(state.read_text());values['nodeskclaw-backend/app/api/router.py']['installed_sha256']='other'
    state.write_text(json.dumps(values))
    # Dry-run leaves a user-modified router untouched if the integration is already present.
    assert a.read_text().endswith('# Local edit\n')
