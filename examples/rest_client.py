"""Internal application example. Never supplies a caller-chosen employee ID.

Environment: MEETING_BASE_URL, MEETING_CLIENT_ID, MEETING_CLIENT_SECRET,
BACKEND_ACCESS_TOKEN. Downloads use --asset-id and --output. Creation uses
--create-json and --idempotency-key, and still requires a human in Portal.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

import httpx


def validate_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise ValueError('MEETING_BASE_URL must be a trusted HTTPS origin without a path')
    return value.rstrip('/')


def validate_download_path(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'/api/v1/downloads/[A-Za-z0-9_-]{1,256}', value):
        raise ValueError('Unexpected download endpoint; refusing to send the access token')
    return value


def required(name: str) -> str:
    value = os.getenv(name, '')
    if not value:
        raise ValueError(f'{name} must be set in the application environment')
    return value


def data(response: httpx.Response) -> dict:
    response.raise_for_status()
    value = response.json()
    if value.get('code') != 0:
        raise RuntimeError(f"Gateway rejected request: {value.get('message_key', 'unknown')}")
    return value['data']


async def run(args: argparse.Namespace) -> None:
    base = validate_base_url(required('MEETING_BASE_URL'))
    scopes = ['meeting.read']
    if args.asset_id:
        scopes.append('meeting.content.download')
    if args.create_json:
        scopes.append('meeting.create.self')
    # Disable proxy inheritance and redirects so credentials cannot be forwarded elsewhere.
    async with httpx.AsyncClient(base_url=base, trust_env=False, follow_redirects=False, timeout=30) as client:
        issued = data(await client.post('/api/v1/auth/exchange', json={
            'client_id': required('MEETING_CLIENT_ID'),
            'client_secret': required('MEETING_CLIENT_SECRET'),
            'subject_token': required('BACKEND_ACCESS_TOKEN'),
            'scopes': scopes, 'resource': base + '/api/v1',
        }))
        client.headers['Authorization'] = 'Bearer ' + issued['access_token']
        if args.create_json:
            if not args.idempotency_key:
                raise ValueError('--idempotency-key is required for create preparation')
            payload = json.loads(Path(args.create_json).read_text(encoding='utf-8'))
            result = data(await client.post('/api/v1/meetings', json=payload,
                                            headers={'Idempotency-Key': args.idempotency_key}))
            # This does not confirm the operation. Only a trusted Portal employee can do that.
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        if args.asset_id:
            if not args.output:
                raise ValueError('--output is required; existing files are never overwritten')
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as output:
                os.chmod(destination, 0o600)
                ticket = data(await client.post(f'/api/v1/assets/{args.asset_id}/download-tickets',
                                                json={'purpose': 'Internal approved application download'}))
                path = validate_download_path(ticket['download_path'])
                async with client.stream('GET', path, timeout=httpx.Timeout(60, read=180)) as response:
                    response.raise_for_status()
                    async for block in response.aiter_bytes(65536):
                        output.write(block)
            print(f'Download finished: {destination}')
            return
        cursor = None
        for _ in range(args.max_pages):
            query = {'limit': 20}
            if cursor:
                query['cursor'] = cursor
            page = data(await client.get('/api/v1/meetings', params=query))
            print(json.dumps(page, ensure_ascii=False, indent=2))
            cursor = page.get('next_cursor')
            if not cursor:
                break
        # sync_coverage remains authoritative: exhausting local pages does not imply full Tencent history.


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-pages', type=int, default=5)
    parser.add_argument('--asset-id')
    parser.add_argument('--output')
    parser.add_argument('--create-json')
    parser.add_argument('--idempotency-key')
    args = parser.parse_args()
    if not 1 <= args.max_pages <= 100 or (args.asset_id and args.create_json):
        parser.error('Choose one operation and a maximum of 1..100 pages')
    try:
        asyncio.run(run(args))
    except (ValueError, OSError, RuntimeError, httpx.HTTPError) as exc:
        # Do not print request bodies, headers, download tokens, or URLs containing them.
        parser.exit(1, f'Operation failed ({type(exc).__name__}); inspect the gateway audit by trace ID.\n')


if __name__ == '__main__':
    main()
