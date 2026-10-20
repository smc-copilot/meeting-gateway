#!/usr/bin/env python3
"""汇总本次联调回执。没有证据的检查保留 NOT_RUN；不把 202、SKIPPED 当通过。"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
from call import private_write,PIN

CASES={
'DEPLOY':'服务器版本、容器、API/Worker 公网出口和 HTTPS 配置人工核对',
'READY':'网关数据库就绪且 Backend 可达',
'IDENTITY':'真实 Backend 员工身份解析',
'AKSK-LIST':'自建应用只读诊断实际调用腾讯',
'WEBHOOK':'腾讯控制台 URL 验证及订阅配置',
'STS':'STS 请求与回调关联，状态 ACTIVE',
'OAUTH-ACTIVE':'OAuth 员工确认完成，连接 ACTIVE',
'OAUTH-USER':'OAuth 用户信息验证通过',
'AKSK-QUERY':'自建通道指定会议录制查询作业成功',
'OAUTH-QUERY':'OAuth 通道指定会议录制查询作业成功',
'SAMPLE-MATCH':'双通道返回会议与指定腾讯样本核对',
'AKSK-TRANSCRIPT':'自建通道完整转写读取',
'AKSK-MINUTES':'自建通道原生纪要读取',
'OAUTH-TRANSCRIPT':'OAuth 通道完整转写读取',
'OAUTH-MINUTES':'OAuth 通道原生纪要读取',
'DOWNLOAD':'实际媒体下载、字节与权限核验',
'CREATE':'可选真实会议创建操作成功',
'CREATE-MATCH':'腾讯客户端核对创建结果与参数',
'EVENT':'真实资源事件到内部系统、验签与资源匹配',
'DENY':'未授权员工不能读取目标内容',
'MCP':'成员身份MCP握手、工具调用和受众隔离（不含完整智能体委托）'}
AUTH=['DEPLOY','READY','IDENTITY','AKSK-LIST','WEBHOOK','STS','OAUTH-ACTIVE','OAUTH-USER']
READ=AUTH+['AKSK-QUERY','OAUTH-QUERY','SAMPLE-MATCH','AKSK-TRANSCRIPT','AKSK-MINUTES','OAUTH-TRANSCRIPT','OAUTH-MINUTES','DENY']
SCOPES={'authorization':AUTH,'read':READ,'ecosystem':READ+['DOWNLOAD','CREATE','CREATE-MATCH','EVENT'],'mcp':READ+['MCP']}


def gate(required, rows):
    states=[rows.get(k,{}).get('status','NOT_RUN') for k in required]
    if any(s=='FAILED' for s in states):return 'FAILED'
    return 'PASSED' if all(s=='PASSED' for s in states) else 'BLOCKED'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scope',choices=SCOPES,default='authorization')
    p.add_argument('--evidence',default='evidence')
    p.add_argument('--manual',default='manual-checks.json')
    p.add_argument('--out',default='生态联调报告.md')
    a=p.parse_args();root=Path(a.evidence).resolve();rows={}
    for file in sorted(root.glob('*.receipt.json')):
        obj=json.loads(file.read_text())
        if obj.get('step') not in CASES:continue
        source=obj.get('source') or {}
        if source.get('commit')!=PIN or source.get('tracked_dirty') or obj.get('transport')!='HTTPS':
            obj['status']='BLOCKED'
        obj['evidence_file']=file.name;obj['evidence_sha256']=hashlib.sha256(file.read_bytes()).hexdigest()
        prev=rows.get(obj['step'])
        if prev is None or obj.get('timestamp','')>=prev.get('timestamp',''):rows[obj['step']]=obj
    manual=Path(a.manual)
    doc={}
    if manual.exists():
        doc=json.loads(manual.read_text())
        for key,obj in doc.get('checks',{}).items():
            if key not in CASES:continue
            if obj.get('status')=='PASSED':
                valid=doc.get('source_commit')==PIN and bool(doc.get('operator')) and bool(obj.get('evidence_files'))
                for rel in obj.get('evidence_files',[]):
                    file=(root/rel).resolve()
                    if not file.is_relative_to(root) or not file.is_file() or (root/rel).is_symlink():valid=False
                if not valid:obj={**obj,'status':'BLOCKED','reason':'MISSING_OPERATOR_OR_EVIDENCE'}
            if obj.get('status') not in {'NOT_RUN','PASSED','FAILED','BLOCKED','SKIPPED'}:obj['status']='BLOCKED'
            # 未填写的人工项不覆盖已有自动回执。
            if obj.get('status')!='NOT_RUN':rows[key]=obj
    required=SCOPES[a.scope];result=gate(required,rows)
    text=['# 腾讯会议 × Meeting Gateway × 内部系统：生态联调报告','',
          f'- 代码版本：`{PIN}`',f'- 报告时间：{datetime.now(timezone.utc).isoformat()}',
          f"- 执行人：{doc.get('operator') or '未填写'}",
          f"- 被测服务器：{doc.get('server') or '未填写'}",
          f"- 内部系统：{doc.get('internal_system') or '未填写'}",
          f'- 验收范围：`{a.scope}`',f'- 本范围结论：**{result}**','',
          'PASSED 仅表示本报告列明的检查；未执行项不代表通过，不等同于全系统生产验收。','',
          '| 检查 | 内容 | 本范围必需 | 结果 | 证据 |','|---|---|---|---|---|']
    for key,description in CASES.items():
        row=rows.get(key,{})
        evidence=row.get('evidence_file') or ', '.join(row.get('evidence_files',[])) or '无'
        text.append(f"| {key} | {description} | {'是' if key in required else '否'} | {row.get('status','NOT_RUN')} | {evidence} |")
    text+=['','## 判定与复测','',
           'BLOCKED：缺少所选范围的必需证据，或发生等待、超时、版本/传输校验不满足。',
           'FAILED：存在明确失败的必需检查。修复后保留旧回执，以新回执重新生成报告。',
           '人工项须记录执行人、实际现象和相对 evidence/ 的脱敏证据路径。不得放入 .env、令牌、应用密钥、完整会议正文或签名下载地址。','']
    private_write(a.out,'\n'.join(text).encode())
    private_write(str(a.out)+'.json',json.dumps({'source_commit':PIN,'scope':a.scope,'status':result,'checks':rows},ensure_ascii=False,indent=2).encode())
    print('报告：'+a.out+'；结论：'+result)
    return 0 if result=='PASSED' else 1
if __name__=='__main__':raise SystemExit(main())
