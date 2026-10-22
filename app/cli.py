"""Explicit, local deployment configuration helpers. No Tencent writes are performed."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit


def generate_env(path: Path, public_url: str, portal_url: str, login_url: str, database_host='postgres'):
    public_url=public_url.rstrip('/');portal_url=portal_url.rstrip('/')
    for value in (public_url,portal_url):
        parsed=urlsplit(value)
        if parsed.scheme!='https' or not parsed.hostname or parsed.query or parsed.fragment or parsed.username or parsed.path:
            raise ValueError('Public and Portal URLs must be HTTPS origins without path, credentials, query or fragment')
    if not database_host or any(ch not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_' for ch in database_host):
        raise ValueError('Invalid database hostname')
    password=secrets.token_hex(24)
    values={'ENVIRONMENT':'production','POSTGRES_PASSWORD':password,
        'DATABASE_URL':f'postgresql+asyncpg://meeting:{password}@{database_host}:5432/meeting',
        'IDENTITY_MODE':'tencent_oauth','ACCOUNT_LOGIN_URL':login_url,
        'ACCOUNT_LOGIN_ALLOW_PRIVATE_HTTP':'false','MEETING_COMPONENT_ID':'meeting-gateway',
        'MEETING_ORG_ID':'','MEETING_BOOTSTRAP_ADMIN_USER_IDS':'[]','AUTH_SESSION_TTL_SECONDS':'900',
        'AUTH_ADMIN_FRESH_SECONDS':'300','TENCENT_MEETING_AUTH_MODE':'oauth','TENCENT_MEETING_CORP_ID':'',
        'TENCENT_MEETING_APP_ID':'','TENCENT_MEETING_APP_SECRET':'',
        'TENCENT_MEETING_APP_SECRET_ID':'','TENCENT_MEETING_APP_SECRET_KEY':'',
        'TENCENT_MEETING_APP_SDK_ID':'','TENCENT_MEETING_APP_OPERATOR_ID':'',
        'TENCENT_MEETING_ALLOWED_OPEN_CORP_IDS':'[]',
        'TENCENT_MEETING_OAUTH_RETURN_URIS':'[]','TENCENT_MEETING_WEBHOOK_NAME':'',
        'TENCENT_MEETING_WEBHOOK_EncodingAESKey':'','TENCENT_MEETING_WEBHOOK_Token':'',
        'TENCENT_MEETING_WEBHOOK_URL':'',
        'METRICS_TOKEN':secrets.token_urlsafe(48),'PUBLIC_BASE_URL':public_url,'PORTAL_BASE_URL':portal_url,
        'KEYRING_JSON':json.dumps({'v1':base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}),
        'ACTIVE_KEY_ID':'v1','ALLOWED_HOSTS':json.dumps([urlsplit(public_url).hostname,'127.0.0.1','localhost']),
        'CORS_ORIGINS':json.dumps([portal_url]),'MCP_ORIGINS':json.dumps([portal_url]),
        'STORAGE_PATH':'/data/private','MEDIA_ALLOWED_HOSTS':'[]','NOTIFICATION_ALLOWED_HOSTS':'[]',
        'NOTIFICATION_ALLOWED_NETWORKS':'[]','MEETING_ENABLED':'true','MEETING_MCP_ENABLED':'false',
        'MEETING_CREATE_ENABLED':'false','MEETING_CORP_SYNC_ENABLED':'false','MEETING_MEDIA_DOWNLOAD_ENABLED':'false'}
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w',encoding='utf-8') as handle:
        for key,value in values.items():handle.write(f'{key}={value}\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    create=sub.add_parser('generate-env')
    create.add_argument('--output',type=Path,default=Path('.env'))
    create.add_argument('--public-base-url',required=True)
    create.add_argument('--portal-base-url',required=True)
    create.add_argument('--backend-url',default='')
    create.add_argument('--account-login-url',default='http://127.0.0.1:9/api/v1/auth/account-login')
    create.add_argument('--database-host',default='postgres')
    sub.add_parser('check')
    sub.add_parser('reconcile-env')
    migrate=sub.add_parser('identity-migrate')
    migrate.add_argument('--map',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.command=='generate-env':
            generate_env(args.output,args.public_base_url,args.portal_base_url,args.account_login_url,args.database_host)
            print(f'Created {args.output}; keep it private. No credentials were printed. Fill organization id and Tencent secret only on the server.')
        elif args.command=='identity-migrate':
            import asyncio
            from app.core.config import Settings
            from app.runtime import Runtime
            rows=json.loads(args.map.read_text(encoding='utf-8'))
            runtime=Runtime(Settings())
            try:
                result=asyncio.run(runtime.identity.apply_legacy_map(rows))
            finally:
                asyncio.run(runtime.close())
            print(json.dumps({'mapped':result['mapped']}))
        elif args.command=='reconcile-env':
            import asyncio
            from app.core.config import Settings
            from app.runtime import Runtime
            from sqlalchemy import select
            from app.models import Application
            runtime=Runtime(Settings())
            async def reconcile():
                async with runtime.db.transaction() as session:
                    deployment=await runtime.identity.ensure_deployment(session)
                    app=await session.scalar(select(Application).where(Application.org_id==deployment.org_id,
                        Application.sdk_id==runtime.settings.tencent_meeting_app_id, Application.deleted_at.is_(None)))
                    if app is None:
                        return {'configured':False}
                    return {'configured':True,'application_id':app.id,'receiver_id':app.receiver_id,
                        'oauth_callback_url':runtime.settings.fixed_oauth_callback_url(),
                        'webhook_callback_url':runtime.settings.fixed_webhook_callback_url()}
            try:
                print(json.dumps(asyncio.run(reconcile())))
            finally:
                asyncio.run(runtime.close())
        else:
            from app.core.config import Settings
            settings=Settings()
            print(json.dumps({'valid':True,'environment':settings.environment,'public_base_url':settings.public_base_url,
                'key_ids':list(settings.keyring_json),'active_key_id':settings.active_key_id,
                'tencent':{'configured':settings.tencent_webhook_complete(),
                    'oauth_callback_url':settings.fixed_oauth_callback_url(),
                    'webhook_callback_url':settings.fixed_webhook_callback_url(),
                    'webhook_url_matches':bool(settings.tencent_meeting_app_id) and settings.tencent_meeting_webhook_url==settings.fixed_webhook_callback_url()},
                'features':{'mcp':settings.meeting_mcp_enabled,'create':settings.meeting_create_enabled,
                    'corp_sync':settings.meeting_corp_sync_enabled,'media_download':settings.meeting_media_download_enabled}}))
    except FileExistsError:
        parser.exit(1,'Refusing to overwrite an existing environment file.\n')
    except Exception:
        # Configuration validation exceptions can include submitted credentials; never print them.
        parser.exit(1,'Configuration failed validation. Check the documented required fields; secret values are not logged.\n')

if __name__=='__main__':main()
