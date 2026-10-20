#!/usr/bin/env python3
"""从本地凭据文件构造 /api/v1/auth/exchange 请求，不执行网络操作。"""
import argparse
import json
import os
from pathlib import Path
from call import private_write
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--client-response',required=True)
p.add_argument('--subject-token',required=True)
p.add_argument('--out',required=True)
p.add_argument('--resource',default=(os.getenv('MEETING_BASE_URL','').rstrip('/')+'/api/v1'))
p.add_argument('--scopes',nargs='+',default=['meeting.read','meeting.content.read','meeting.content.download'])
a=p.parse_args()
try:
    c=json.loads(Path(a.client_response).read_text())['data']
    body={'client_id':c['id'],'client_secret':c['client_secret'],
          'subject_token':Path(a.subject_token).read_text().strip(),'scopes':a.scopes,'resource':a.resource}
    if not body['subject_token'] or not body['resource'].startswith('https://'):raise ValueError()
    private_write(a.out,json.dumps(body,ensure_ascii=False,indent=2).encode())
    print('已保存：'+a.out)
except Exception:raise SystemExit('请求文件生成失败；检查输入文件，未输出凭据。')
