"""FastAPI factory: uvicorn app.main:create_app --factory. Schema migrations run separately."""
from contextlib import asynccontextmanager
import hmac
import logging
from fastapi import FastAPI,Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse,Response
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import IntegrityError
from app.__init__ import __version__
from app.core.config import Settings
from app.core.errors import MeetingError
from app.core.middleware import GatewayMiddleware
from app.runtime import Runtime
from app.api.router import router as api_router
from app.authorization.router import router as authorization_router
from app.callbacks.router import router as callback_router
from app.mcp.server import router as mcp_router

logger=logging.getLogger(__name__)


def create_app(settings=None,*,runtime=None):
    owned=runtime is None
    rt=runtime or Runtime(settings or Settings())
    @asynccontextmanager
    async def lifespan(app):
        yield
        if owned:await rt.close()
    app=FastAPI(title='NoDeskClaw Meeting Gateway',version=__version__,lifespan=lifespan,
        docs_url='/docs' if rt.settings.environment!='production' else None,
        redoc_url=None,openapi_url='/openapi.json' if rt.settings.environment!='production' else None)
    app.state.runtime=rt
    app.add_middleware(CORSMiddleware,allow_origins=rt.settings.cors_origins,allow_credentials=False,
        allow_methods=['GET','POST','PUT','OPTIONS'],allow_headers=['Authorization','Content-Type','Idempotency-Key','X-Request-ID','Range'],
        expose_headers=['X-Request-ID','Content-Disposition','Content-Range'])
    app.add_middleware(GatewayMiddleware,runtime=rt)
    app.include_router(api_router,prefix='/api/v1')
    app.include_router(authorization_router)
    app.include_router(callback_router)
    app.include_router(mcp_router)

    @app.exception_handler(MeetingError)
    async def meeting_error(request:Request,exc:MeetingError):
        trace=getattr(request.state,'trace_id','')
        headers={}
        if exc.retry_after:headers['Retry-After']=str(exc.retry_after)
        if exc.status==401:
            suffix='/mcp' if request.url.path.startswith('/mcp') else '/api/v1'
            headers['WWW-Authenticate']='Bearer resource_metadata="'+rt.settings.public_base_url+'/.well-known/oauth-protected-resource'+suffix+'"'
        p=getattr(request.state,'principal',None)
        if p:
            try:
                from app.services.audit_service import record
                async with rt.db.transaction() as s:record(s,p,'request.denied',decision='DENY',reason=exc.reason)
            except Exception:logger.warning('audit.denial_write_failed trace_id=%s',trace)
        return JSONResponse(jsonable_encoder(exc.payload(trace)),status_code=exc.status,headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request:Request,exc):
        return await meeting_error(request,MeetingError('INVALID_REQUEST',422))

    @app.exception_handler(IntegrityError)
    async def integrity_error(request:Request,exc):
        return await meeting_error(request,MeetingError('CONFLICT',409))

    @app.exception_handler(Exception)
    async def internal_error(request:Request,exc):
        # Deliberately omit exception messages: provider URLs may contain short-lived credentials.
        logger.error('request.failed trace_id=%s type=%s',getattr(request.state,'trace_id',''),type(exc).__name__)
        return await meeting_error(request,MeetingError('INTERNAL_ERROR',500))

    @app.get('/health/live',tags=['health'])
    async def live():return {'status':'ok'}

    @app.get('/health/ready',tags=['health'])
    async def ready():
        db=await rt.db.ready()
        return JSONResponse({'status':'ok' if db else 'unavailable','database':db,'backend':False},status_code=200 if db else 503)

    @app.get('/metrics',include_in_schema=False)
    async def metrics(request:Request):
        expected=rt.settings.metrics_token.get_secret_value()
        if not expected or not hmac.compare_digest(request.headers.get('authorization',''),'Bearer '+expected):
            raise MeetingError('RESOURCE_NOT_ACCESSIBLE',404)
        output=''.join('nodeskclaw_meeting_'+key+' '+str(value)+'\n' for key,value in sorted(rt.metrics.items()) if key.replace('_','').isalnum())
        return Response(output,media_type='text/plain; version=0.0.4')

    return app
