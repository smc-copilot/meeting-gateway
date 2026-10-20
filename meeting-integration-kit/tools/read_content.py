#!/usr/bin/env python3
"""读取网关完整转写或纪要；保存到 private，报告只保存数量、版本摘要与状态。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import quote
from call import perform,private_write,source_identity


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kind',choices=['transcript','minutes'],required=True)
    p.add_argument('--recording-id',required=True)
    p.add_argument('--auth-file',required=True)
    p.add_argument('--label',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--base',default=os.getenv('MEETING_BASE_URL'))
    p.add_argument('--repo',default=os.getenv('MEETING_REPO'))
    p.add_argument('--evidence',default='evidence')
    p.add_argument('--seconds',type=int,default=600)
    a=p.parse_args()
    source=source_identity(a.repo)
    receipt={'step':a.label,'source':source,'timestamp':datetime.now(timezone.utc).isoformat(),'status':'FAILED','transport':'HTTPS'}
    target='/api/v1/recordings/'+quote(a.recording_id,safe='')+'/'+a.kind
    def get(path):
        status,raw,trace,_=perform(a.base,path,token=Path(a.auth_file).read_text().strip())
        private_write(str(a.out)+'.last-response.json',raw)
        obj=json.loads(raw)
        receipt.update(http_status=status,trace_id=trace)
        if status not in {200,202} or obj.get('code',0)!=0:raise ValueError('HTTP_OR_BUSINESS_FAILURE')
        return status,obj['data']
    try:
        status,data=get(target+'?fetch=ensure')
        if status==202:
            job_id=data['job_id'];stop=time.monotonic()+a.seconds
            while True:
                if time.monotonic()>stop:raise TimeoutError()
                _,job=get('/api/v1/jobs/'+quote(job_id,safe=''))
                state=job.get('state')
                if state=='SUCCEEDED':break
                if state in {'FAILED','CANCELLED'}:raise ValueError('JOB_FAILED')
                time.sleep(3)
            status,data=get(target+'?fetch=cache')
        version=None;paragraphs=[];pages=0;seen=set();last_data=None
        while True:
            if data.get('state')!='READY' or data.get('is_complete') is not True:raise ValueError('CONTENT_INCOMPLETE')
            current=data.get('content_version')
            if not current or (version and current!=version):raise ValueError('CONTENT_VERSION_CHANGED')
            version=current;pages+=1;last_data=data
            if a.kind=='transcript':
                rows=data['content']['paragraphs']
                if not isinstance(rows,list):raise ValueError('CONTENT_SCHEMA_ERROR')
                paragraphs.extend(rows)
            else:
                if not str(data['content'].get('minute','')).strip():raise ValueError('EMPTY_MINUTES')
            cursor=data.get('next_cursor')
            if not cursor:break
            if a.kind!='transcript' or cursor in seen or pages>10000:raise ValueError('CURSOR_ERROR')
            seen.add(cursor)
            _,data=get(target+'?fetch=cache&limit=100&cursor='+quote(cursor,safe=''))
        if a.kind=='transcript':
            if not paragraphs:raise ValueError('EMPTY_TRANSCRIPT')
            last_data['content']['paragraphs']=paragraphs
        last_data['next_cursor']=None
        raw=json.dumps(last_data,ensure_ascii=False,indent=2).encode()
        private_write(a.out,raw)
        receipt.update(status='PASSED',recording_id=a.recording_id,asset_id=last_data['id'],gateway_pages=pages,
                       paragraph_count=len(paragraphs) if a.kind=='transcript' else None,
                       content_version=version,output_sha256=hashlib.sha256(raw).hexdigest())
    except Exception as exc:
        receipt['error_type']=type(exc).__name__
        if isinstance(exc,TimeoutError):receipt['status']='BLOCKED'
    private_write(Path(a.evidence)/(a.label+'-'+str(time.time_ns())+'.receipt.json'),json.dumps(receipt,indent=2).encode())
    print(json.dumps({'step':a.label,'status':receipt['status'],'pages':receipt.get('gateway_pages')},ensure_ascii=False))
    return 0 if receipt['status']=='PASSED' else 1
if __name__=='__main__':raise SystemExit(main())
