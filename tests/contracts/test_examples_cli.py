from pathlib import Path
import base64
import importlib.util
import json
import os
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_example(name):
    path = ROOT / 'examples' / (name + '.py')
    assert path.is_file(), f'Missing working example: {path.name}'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rest_example_rejects_untrusted_base_and_cross_origin_download():
    module = load_example('rest_client')
    with pytest.raises(ValueError):
        module.validate_base_url('http://meeting.example.org')
    assert module.validate_base_url('https://meeting.example.org/') == 'https://meeting.example.org'
    with pytest.raises(ValueError):
        module.validate_download_path('//attacker.example/x')
    with pytest.raises(ValueError):
        module.validate_download_path('/oauth/token')
    assert module.validate_download_path('/api/v1/downloads/md_test') == '/api/v1/downloads/md_test'


def test_mcp_example_has_explicit_protocol_and_checks_json_rpc_errors():
    module = load_example('mcp_client')
    assert module.PROTOCOL_VERSION == '2025-11-25'
    with pytest.raises(RuntimeError):
        module.check_result({'jsonrpc':'2.0', 'id':1, 'error':{'code':-32602, 'message':'bad'}})
    with pytest.raises(RuntimeError):
        module.check_result({'jsonrpc':'2.0', 'id':1, 'result':{'isError':True}})
    assert module.check_result({'jsonrpc':'2.0', 'id':1, 'result':{'tools':[]}}) == {'tools':[]}


def test_event_example_verifies_exact_bytes_and_commits_idempotently(tmp_path):
    import hashlib
    import hmac
    module = load_example('webhook_consumer')
    secret = 's' * 40
    body = json.dumps({'event_id':'event-1','event_type':'meeting.updated','resource_id':'r1','occurred_at':'2026-10-16T00:00:00Z'}, separators=(',',':')).encode()
    signature = 'sha256=' + hmac.new(secret.encode(), b'1000.nonce-1.' + body, hashlib.sha256).hexdigest()
    module.verify_signature(secret, '1000', 'nonce-1', signature, body, now=1000)
    with pytest.raises(ValueError):
        module.verify_signature(secret, '1000', 'nonce-1', signature, body+b' ', now=1000)
    with pytest.raises(ValueError):
        module.verify_signature(secret, '1000', 'nonce-1', signature, body, now=1301)
    path = tmp_path / 'inbox.db'
    assert module.persist_event(path, body, 'nonce-1', now=1000) is True
    assert module.persist_event(path, body, 'nonce-2', now=1001) is False
    with pytest.raises(ValueError):
        module.persist_event(path, body.replace(b'r1',b'r2'), 'nonce-3', now=1002)


def test_generate_env_never_overwrites_and_contains_valid_random_keys(tmp_path):
    target = tmp_path / '.env'
    cmd = [sys.executable, '-m', 'app.cli', 'generate-env', '--output', str(target),
           '--public-base-url', 'https://meeting.example.org', '--portal-base-url', 'https://portal.example.org',
           '--backend-url', 'http://backend:8000', '--database-host', 'postgres']
    first = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    values = dict(line.split('=',1) for line in target.read_text().splitlines() if line and not line.startswith('#'))
    assert values['IDENTITY_MODE'] == 'account_login'
    assert 'BACKEND_SERVICE_TOKEN' not in values
    assert len(values['METRICS_TOKEN']) >= 32
    assert values['METRICS_TOKEN'] not in first.stdout
    keys = json.loads(values['KEYRING_JSON'])
    assert all(len(base64.urlsafe_b64decode(v)) == 32 for v in keys.values())
    assert os.stat(target).st_mode & 0o777 == 0o600
    old = target.read_bytes()
    second = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    assert second.returncode != 0
    assert target.read_bytes() == old
