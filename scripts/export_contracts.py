#!/usr/bin/env python3
"""Regenerate contracts from code. Uses an isolated test configuration, no network or provider calls."""
import base64
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.core.config import Settings
from app.main import create_app
from app.mcp.tools import TOOL_DEFINITIONS
from app.services.event_service import EVENT_TYPES

ROOT=Path(__file__).resolve().parents[1]

def write(path,value):
    target=ROOT/path;target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

with tempfile.TemporaryDirectory() as directory:
    settings=Settings(environment='test',database_url='sqlite://',keyring_json={'v1':base64.urlsafe_b64encode(b'c'*32).decode()},
        storage_path=Path(directory),public_base_url='https://meeting.example.org',portal_base_url='https://portal.example.org')
    app=create_app(settings)
    schema=app.openapi()
    schema['info']['description']='Generated source contract; example.org is illustrative. Credentials and tenancy are resolved by the gateway.'
    write('contracts/internal-rest/v1/openapi.json',schema)
    frontend={**schema,'paths':{k:v for k,v in schema['paths'].items() if k.startswith('/api/v1/') and not k.startswith('/api/v1/auth/exchange')}}
    write('contracts/frontend/v1/openapi.json',frontend)
    write('contracts/mcp/v1/tools.json',{'protocol_version':'2025-11-25','transport':'streamable-http','tools':[{'name':name,'description':definition[2],'inputSchema':definition[0].model_json_schema(),'outputSchema':{'type':'object','additionalProperties':True},'annotations':{'readOnlyHint':definition[3],'destructiveHint':False,'openWorldHint':True,'idempotentHint':name!='meeting_download_request'}} for name,definition in TOOL_DEFINITIONS.items()]})
    write('contracts/events/v1/envelope.schema.json',{'$schema':'https://json-schema.org/draft/2020-12/schema',
        'type':'object','required':['event_id','event_type','resource_id','occurred_at'],
        'properties':{'event_id':{'type':'string'},'event_type':{'enum':sorted(EVENT_TYPES)},
            'resource_id':{'type':'string'},'occurred_at':{'type':'string','format':'date-time'},'version':{'type':'integer'},'state':{'type':'string'},'asset_type':{'type':'string'},'trace_id':{'type':'string'}}})
    import asyncio
    asyncio.run(app.state.runtime.close())
print('Contracts generated from registered routes and tool definitions.')
