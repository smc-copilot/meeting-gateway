#!/usr/bin/env python3
"""消费网关下载许可；流式写入私有文件，不打印下载票据或 URL。"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.request
from call import NoRedirect,make_url,private_write,source_identity
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--ticket-json',required=True)
p.add_argument('--auth-file',required=True)
p.add_argument('--out',required=True)
p.add_argument('--base',default=os.getenv('MEETING_BASE_URL'))
p.add_argument('--repo',default=os.getenv('MEETING_REPO'))
p.add_argument('--range')
p.add_argument('--max-bytes',type=int,default=2147483648)
p.add_argument('--evidence',default='evidence')
a=p.parse_args()
try:
    source=source_identity(a.repo)
    path=json.loads(Path(a.ticket_json).read_text())['data']['download_path']
    if not re.fullmatch(r'/api/v1/downloads/[A-Za-z0-9_-]{1,256}',path):raise ValueError()
    if a.range and not re.fullmatch(r'bytes=[0-9]+-[0-9]*',a.range):raise ValueError()
    output=Path(a.out);output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if output.exists() or output.is_symlink():raise ValueError()
    temporary=Path(str(output)+'.part')
    headers={'Authorization':'Bearer '+Path(a.auth_file).read_text().strip()}
    if a.range:headers['Range']=a.range
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    request=urllib.request.Request(make_url(a.base,path),headers=headers)
    count=0;digest=hashlib.sha256()
    # .part 失败后保留供操作员判断；不伪装成完整文件。
    with opener.open(request,timeout=180) as response,temporary.open('xb') as handle:
        os.chmod(temporary,0o600)
        if response.status!=(206 if a.range else 200):raise ValueError()
        if a.range and not response.headers.get('Content-Range'):raise ValueError()
        while True:
            block=response.read(65536)
            if not block:break
            count+=len(block)
            if count>a.max_bytes:raise ValueError()
            handle.write(block);digest.update(block)
        length=response.headers.get('Content-Length')
        if not count or (length and count!=int(length)):raise ValueError()
        receipt={'step':'DOWNLOAD-HTTP','source':source,'timestamp':datetime.now(timezone.utc).isoformat(),
                 'transport':'HTTPS','status':'PASSED','http_status':response.status,'bytes':count,
                 'sha256':digest.hexdigest(),'range':a.range,'content_range':response.headers.get('Content-Range'),
                 'trace_id':response.headers.get('X-Request-ID')}
    os.replace(temporary,output)
    private_write(Path(a.evidence)/('download-'+str(time.time_ns())+'.json'),json.dumps(receipt,indent=2).encode())
    print(json.dumps({'status':'PASSED','bytes':count,'sha256':digest.hexdigest()}))
except Exception as exc:
    print(json.dumps({'status':'FAILED','error_type':type(exc).__name__}))
    raise SystemExit(1)
