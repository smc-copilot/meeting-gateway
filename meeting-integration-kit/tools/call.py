#!/usr/bin/env python3
"""受控 HTTP 调用与脱敏回执；不重试写请求，不跟随重定向，不使用系统 HTTP 代理。"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

PIN = '79e22d08b623a4f7816db05af631a463fe14348b'
MISSING = object()
MAX_BYTES = 20 * 1024 * 1024


def private_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError('Refusing symlink output')
    fd, temporary = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def get_path(value, path):
    current = value
    for part in path.split('.'):
        if isinstance(current, dict) and part in current: current = current[part]
        elif isinstance(current, list) and part.isdecimal() and int(part) < len(current): current = current[int(part)]
        else: return MISSING
    return current


def check_assertions(payload, equalities, nonempty):
    checks = []
    for rule in equalities:
        key, sep, text = rule.partition('=')
        if not sep or re.search(r'token|secret|password|authorization|cipher', key, re.I):
            raise ValueError('Unsafe or invalid assertion')
        try: expected = json.loads(text)
        except ValueError: expected = text
        actual = get_path(payload, key)
        matches = actual is not MISSING and type(actual) is type(expected) and actual == expected
        checks.append({'field': key, 'operator': 'equals', 'matched': matches})
    for key in nonempty:
        if re.search(r'token|secret|password|authorization|cipher', key, re.I):
            raise ValueError('Unsafe assertion')
        value = get_path(payload, key)
        checks.append({'field': key, 'operator': 'nonempty', 'matched': value is not MISSING and bool(value)})
    return checks


def classify(status, expected, checks):
    if status not in expected or not all(c['matched'] for c in checks): return 'FAILED'
    if status == 202: return 'ACCEPTED'
    return 'PASSED'


def make_url(base, path, allow_http=False):
    p = urllib.parse.urlsplit(base)
    if (p.scheme not in ({'https','http'} if allow_http else {'https'}) or not p.hostname
        or p.username or p.password or p.query or p.fragment or p.path not in ('','/')):
        raise ValueError('Base must be an HTTPS origin; credentials and paths forbidden')
    if not path.startswith('/') or path.startswith('//') or '#' in path or '\\' in path or any(ord(x)<32 for x in path):
        raise ValueError('Path must remain on the configured origin')
    return base.rstrip('/') + path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def source_identity(repo):
    if not repo: raise ValueError('MEETING_REPO is required')
    sha = subprocess.check_output(['git','-C',repo,'rev-parse','HEAD'], text=True, stderr=subprocess.DEVNULL).strip()
    dirty = bool(subprocess.check_output(['git','-C',repo,'status','--porcelain','--untracked-files=no'], text=True, stderr=subprocess.DEVNULL).strip())
    if sha != PIN: raise ValueError('Repository does not match the documented commit')
    return {'commit': sha, 'tracked_dirty': dirty}


def perform(base, path, *, method='GET', token=None, body=None, idempotency_key=None, allow_http=False, timeout=30):
    url = make_url(base, path, allow_http)
    headers = {'Accept':'application/json', 'X-Request-ID':str(uuid.uuid4())}
    if token:
        if '\n' in token or '\r' in token: raise ValueError('Invalid token file')
        headers['Authorization'] = 'Bearer ' + token
    if body is not None: headers['Content-Type'] = 'application/json'
    if idempotency_key: headers['Idempotency-Key'] = idempotency_key
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    start = time.monotonic()
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES: raise ValueError('Response exceeds bounded JSON size')
        status = response.code
        trace = response.headers.get('X-Request-ID','')
    return status, raw, trace, round((time.monotonic()-start)*1000)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default=os.getenv('MEETING_BASE_URL'))
    parser.add_argument('--repo', default=os.getenv('MEETING_REPO'))
    parser.add_argument('--path', required=True)
    parser.add_argument('--method', choices=['GET','POST','PUT'], default='GET')
    parser.add_argument('--auth-file')
    parser.add_argument('--no-auth', action='store_true')
    parser.add_argument('--json', dest='input_file')
    parser.add_argument('--idempotency-key')
    parser.add_argument('--expect-status', default='200')
    parser.add_argument('--equals', action='append', default=[])
    parser.add_argument('--notempty', action='append', default=[])
    parser.add_argument('--label', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--evidence', default='evidence')
    parser.add_argument('--allow-http', action='store_true', help='仅供明确批准的内网或本地测试；报告标记 INSECURE_HTTP')
    args=parser.parse_args()
    try:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',args.label): raise ValueError('Invalid label')
        if not args.base or (bool(args.auth_file)==bool(args.no_auth)): raise ValueError('Select token file or no-auth')
        source=source_identity(args.repo)
        token=Path(args.auth_file).read_text().strip() if args.auth_file else None
        if args.auth_file and not token: raise ValueError('Token file empty')
        body=Path(args.input_file).read_bytes() if args.input_file else None
        if body is not None:
            json.loads(body)
            if args.method=='GET': raise ValueError('GET request body forbidden')
        checks=check_assertions({},args.equals,args.notempty)  # validate assertion syntax before sending
        expected={int(s) for s in args.expect_status.split(',')}
        receipt={'step':args.label,'source':source,'timestamp':datetime.now(timezone.utc).isoformat(),
                 'method':args.method,'transport':'HTTPS' if args.base.startswith('https://') else 'INSECURE_HTTP',
                 'status':'FAILED','checks':checks,'http_status':None,'trace_id':None}
        try:
            status,raw,trace,elapsed=perform(args.base,args.path,method=args.method,token=token,body=body,
                idempotency_key=args.idempotency_key,allow_http=args.allow_http)
            private_write(args.out,raw)
            payload=json.loads(raw)
            checks=check_assertions(payload,args.equals,args.notempty)
            receipt.update(status=classify(status,expected,checks),checks=checks,http_status=status,
                trace_id=trace,elapsed_ms=elapsed,response_sha256=hashlib.sha256(raw).hexdigest(),response_bytes=len(raw))
        except (urllib.error.URLError,TimeoutError,OSError,ValueError) as error:
            receipt['error_type']=type(error).__name__  # 不打印异常正文或返回体
        directory=Path(args.evidence);directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        target=directory/(args.label+'-'+str(time.time_ns())+'.receipt.json')
        private_write(target,json.dumps(receipt,ensure_ascii=False,indent=2).encode())
        print(json.dumps({'step':args.label,'status':receipt['status'],'http_status':receipt['http_status'],
                          'receipt':str(target)},ensure_ascii=False))
        return 0 if receipt['status'] in {'PASSED','ACCEPTED'} else 1
    except (OSError,ValueError,subprocess.SubprocessError):
        print('CONFIGURATION_ERROR: 检查版本、文件、参数；未输出凭证。',file=__import__('sys').stderr)
        return 2

if __name__=='__main__': raise SystemExit(main())
