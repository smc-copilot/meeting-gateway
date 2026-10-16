"""Explicit, local deployment configuration helpers. No Tencent writes are performed."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit


def generate_env(path: Path, public_url: str, portal_url: str, backend_url: str, database_host='postgres'):
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
        'NODESKCLAW_BACKEND_URL':backend_url.rstrip('/'),'BACKEND_SERVICE_TOKEN':secrets.token_urlsafe(48),
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
    create.add_argument('--backend-url',default='http://nodeskclaw-backend:8000')
    create.add_argument('--database-host',default='postgres')
    sub.add_parser('check')
    args=parser.parse_args()
    try:
        if args.command=='generate-env':
            generate_env(args.output,args.public_base_url,args.portal_base_url,args.backend_url,args.database_host)
            print(f'Created {args.output}; keep it private. No credentials were printed. Configure the matching Backend identity token.')
        else:
            from app.core.config import Settings
            settings=Settings()
            print(json.dumps({'valid':True,'environment':settings.environment,'public_base_url':settings.public_base_url,
                'key_ids':list(settings.keyring_json),'active_key_id':settings.active_key_id,
                'features':{'mcp':settings.meeting_mcp_enabled,'create':settings.meeting_create_enabled,
                    'corp_sync':settings.meeting_corp_sync_enabled,'media_download':settings.meeting_media_download_enabled}}))
    except FileExistsError:
        parser.exit(1,'Refusing to overwrite an existing environment file.\n')
    except Exception:
        # Configuration validation exceptions can include submitted credentials; never print them.
        parser.exit(1,'Configuration failed validation. Check the documented required fields; secret values are not logged.\n')

if __name__=='__main__':main()
