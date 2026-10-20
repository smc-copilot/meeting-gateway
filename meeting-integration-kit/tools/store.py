#!/usr/bin/env python3
"""在权限 0600 文件中保存交互输入的令牌或 JSON 字段，不向终端输出值。"""
import argparse
import getpass
import json
from pathlib import Path
from call import private_write,get_path,MISSING
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--out',required=True)
p.add_argument('--from-json')
p.add_argument('--field')
a=p.parse_args()
try:
    if a.from_json:
        value=get_path(json.loads(Path(a.from_json).read_text()),a.field or '')
        if value is MISSING or not isinstance(value,str) or not value:raise ValueError()
    else:value=getpass.getpass('粘贴凭证（不回显）：').strip()
    if not value or '\n' in value or '\r' in value:raise ValueError()
    private_write(a.out,(value+'\n').encode())
    print('已保存：'+a.out)
except Exception:
    raise SystemExit('保存失败；未输出输入内容。')
