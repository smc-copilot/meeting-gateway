#!/usr/bin/env python3
"""轮询已受理作业/操作；只 GET，不重新提交，不把超时或 UNKNOWN 当成功。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.error
from call import perform,private_write,source_identity


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kind',choices=['jobs','operations'],default='jobs')
    p.add_argument('--id',required=True)
    p.add_argument('--label',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--auth-file',required=True)
    p.add_argument('--base',default=os.getenv('MEETING_BASE_URL'))
    p.add_argument('--repo',default=os.getenv('MEETING_REPO'))
    p.add_argument('--evidence',default='evidence')
    p.add_argument('--seconds',type=int,default=600)
    a=p.parse_args()
    try:
        if not a.id.replace('-','').isalnum() or not a.label.replace('-','').replace('_','').isalnum(): raise ValueError()
        source=source_identity(a.repo)
        stop=time.monotonic()+a.seconds
        result={'step':a.label,'source':source,'timestamp':datetime.now(timezone.utc).isoformat(),'status':'BLOCKED','transport':'HTTPS'}
        while time.monotonic()<stop:
            # 每轮重读文件，允许操作员在另一终端更新到期令牌。
            status,raw,trace,_=perform(a.base,'/api/v1/'+a.kind+'/'+a.id,token=Path(a.auth_file).read_text().strip())
            private_write(a.out,raw)
            obj=json.loads(raw);data=obj.get('data') or {};state=data.get('state')
            result.update(http_status=status,trace_id=trace,state=state,response_sha256=hashlib.sha256(raw).hexdigest())
            if status!=200 or obj.get('code',0)!=0:
                result['status']='FAILED';break
            if state=='SUCCEEDED': result['status']='PASSED';break
            if state in {'FAILED','CANCELLED','OUTCOME_UNKNOWN','OPERATION_EXPIRED','REJECTED'}:
                result['status']='FAILED';break
            if state=='AWAITING_CONFIRMATION':
                result['status']='BLOCKED';break
            time.sleep(3)
        result['timestamp']=datetime.now(timezone.utc).isoformat()
        private_write(Path(a.evidence)/(a.label+'-'+str(time.time_ns())+'.receipt.json'),json.dumps(result,indent=2).encode())
        print(json.dumps({'step':a.label,'status':result['status'],'state':result.get('state')},ensure_ascii=False))
        return 0 if result['status']=='PASSED' else 1
    except Exception as exc:
        print(json.dumps({'step':a.label,'status':'FAILED','error_type':type(exc).__name__}))
        return 2
if __name__=='__main__':raise SystemExit(main())
