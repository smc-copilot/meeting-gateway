"""Read-only MCP wire example, deliberately independent of SDK version changes.

MEETING_BASE_URL: HTTPS gateway origin.
MEETING_MCP_ACCESS_TOKEN: downstream token with resource=<origin>/mcp,
issued through the registered-client authorization code + PKCE consent flow.
Never substitute Tencent tokens or a Backend login token.
"""
import asyncio
import json
import os
from urllib.parse import urlsplit

import httpx

PROTOCOL_VERSION = '2025-11-25'


def check_result(value: dict) -> dict:
    if value.get('jsonrpc') != '2.0' or 'error' in value:
        raise RuntimeError('MCP JSON-RPC error; inspect the gateway trace')
    result = value.get('result')
    if not isinstance(result, dict) or result.get('isError') is True:
        raise RuntimeError('MCP tool denied or failed; no alternative credential is attempted')
    return result


async def main() -> None:
    base = os.environ['MEETING_BASE_URL'].rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('MEETING_BASE_URL must be a trusted HTTPS origin')
    headers = {
        'Authorization': 'Bearer ' + os.environ['MEETING_MCP_ACCESS_TOKEN'],
        'Accept': 'application/json, text/event-stream',
        'MCP-Protocol-Version': PROTOCOL_VERSION,
    }
    async with httpx.AsyncClient(base_url=base, headers=headers, trust_env=False,
                                follow_redirects=False, timeout=30) as client:
        async def rpc(ident: int, method: str, params: dict) -> dict:
            response = await client.post('/mcp', json={'jsonrpc':'2.0', 'id':ident, 'method':method, 'params':params})
            response.raise_for_status()
            value = response.json()
            if value.get('id') != ident:
                raise RuntimeError('Mismatched JSON-RPC response ID')
            return check_result(value)
        initialized = await rpc(1, 'initialize', {
            'protocolVersion': PROTOCOL_VERSION, 'capabilities': {},
            'clientInfo': {'name':'meeting-readonly-example', 'version':'1.0.0'},
        })
        if initialized['protocolVersion'] != PROTOCOL_VERSION:
            raise RuntimeError('Server negotiated an unsupported protocol')
        notified = await client.post('/mcp', json={'jsonrpc':'2.0', 'method':'notifications/initialized'})
        if notified.status_code != 202:
            raise RuntimeError('Initialization notification was not accepted')
        tools = await rpc(2, 'tools/list', {})
        print(json.dumps(tools, ensure_ascii=False, indent=2))
        if not any(tool['name'] == 'meeting_list' for tool in tools['tools']):
            raise RuntimeError('Current grant does not expose meeting_list')
        listed = await rpc(3, 'tools/call', {'name':'meeting_list', 'arguments':{'limit':20}})
        print(json.dumps(listed['structuredContent'], ensure_ascii=False, indent=2))
        # Tool availability is not permanent authority: each subsequent call is checked again.


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyError, ValueError, RuntimeError, httpx.HTTPError) as exc:
        raise SystemExit(f'MCP request failed ({type(exc).__name__}); no secret-bearing exception is printed.') from None
