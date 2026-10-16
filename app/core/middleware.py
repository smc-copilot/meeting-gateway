"""ASGI guardrails without logging query strings, ticket paths, request bodies or credentials."""
import asyncio
import re
import uuid
from urllib.parse import urlsplit
from starlette.responses import JSONResponse
from app.core.errors import MeetingError

class GatewayMiddleware:
    def __init__(self,app,runtime):
        self.app,self.rt=app,runtime
        self.semaphore=asyncio.Semaphore(runtime.settings.max_http_concurrency)

    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        headers={k.decode('latin1').lower():v.decode('latin1') for k,v in scope['headers']}
        trace=headers.get('x-request-id','')
        if not re.fullmatch(r'[A-Za-z0-9-]{1,64}',trace):trace=str(uuid.uuid4())
        scope.setdefault('state',{})['trace_id']=trace
        async def fail(reason,status):
            response=JSONResponse(MeetingError(reason,status).payload(trace),status_code=status,headers={'Cache-Control':'no-store','X-Request-ID':trace})
            await response(scope,receive,send)
        try:host=urlsplit('//'+headers.get('host','')).hostname
        except ValueError:host=None
        if host not in self.rt.settings.allowed_hosts:return await fail('INVALID_REQUEST',400)
        path=scope.get('path','')
        origin=headers.get('origin')
        allowed=self.rt.settings.mcp_origins if path.startswith('/mcp') else self.rt.settings.cors_origins
        if origin and not path.startswith('/callbacks/tencent/') and origin not in allowed:
            return await fail('PERMISSION_DENIED',403)
        if len(scope.get('query_string',b''))>8192 or len(path)>4096:return await fail('INVALID_REQUEST',414)
        if not self.rt.settings.meeting_enabled and not path.startswith(('/health/','/callbacks/tencent/')):
            return await fail('FEATURE_DISABLED',503)
        total=0;body=[]
        if headers.get('content-length'):
            try:size=int(headers['content-length'])
            except ValueError:return await fail('INVALID_REQUEST',400)
            if size<0 or size>self.rt.settings.max_request_bytes:return await fail('INVALID_REQUEST',413)
        while True:
            event=await receive()
            if event['type']=='http.disconnect':return
            chunk=event.get('body',b'');total+=len(chunk)
            if total>self.rt.settings.max_request_bytes:return await fail('INVALID_REQUEST',413)
            body.append(chunk)
            if not event.get('more_body',False):break
        delivered=False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered=True
                return {'type':'http.request','body':b''.join(body),'more_body':False}
            return await receive()
        async def safe_send(message):
            if message['type']=='http.response.start':
                message['headers']=list(message.get('headers',[]))+[(b'x-request-id',trace.encode()),(b'x-content-type-options',b'nosniff'),(b'referrer-policy',b'no-referrer')]
                if not any(k.lower()==b'cache-control' for k,v in message['headers']):
                    message['headers'].append((b'cache-control',b'no-store'))
                self.rt.metrics['http_'+str(message['status'])]+=1
            await send(message)
        async with self.semaphore:
            await self.app(scope,replay,safe_send)
