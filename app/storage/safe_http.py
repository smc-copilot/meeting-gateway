"""Allow-list plus connect-time DNS pinning. No redirects, no environment HTTP proxy."""
import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit, SplitResult
import aiohttp
from aiohttp.abc import AbstractResolver
from app.core.errors import MeetingError


def validate_url(url: str, allowed_hosts: list[str]) -> SplitResult:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment or parsed.port not in (None, 443):
            raise ValueError("url")
        if not host or host not in {h.lower().rstrip(".") for h in allowed_hosts}:
            raise ValueError("host")
        return parsed
    except (ValueError, TypeError) as exc:
        raise MeetingError("SSRF_BLOCKED", 403) from exc


def validate_ips(addresses: list[str], allowed_networks: list[str] | None = None) -> list[str]:
    networks = [ipaddress.ip_network(value) for value in (allowed_networks or [])]
    if not addresses:
        raise MeetingError("SSRF_BLOCKED", 403)
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        forbidden = ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved
        if forbidden or (not ip.is_global and not any(ip in network for network in networks)):
            raise MeetingError("SSRF_BLOCKED", 403)
    return addresses


class ValidatingResolver(AbstractResolver):
    def __init__(self, allowed_networks=None):
        self.allowed_networks = allowed_networks or []

    async def resolve(self, host, port=0, family=socket.AF_INET):
        entries = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM, family=family)
        addresses = list(dict.fromkeys(entry[4][0] for entry in entries))
        validate_ips(addresses, self.allowed_networks)
        return [{"hostname": host, "host": address, "port": port,
                 "family": socket.AF_INET6 if ":" in address else socket.AF_INET,
                 "proto": 0, "flags": socket.AI_NUMERICHOST} for address in addresses]

    async def close(self):
        return None


class SafeHTTP:
    def __init__(self, allowed_hosts: list[str], *, allowed_networks=None):
        self.allowed_hosts = allowed_hosts
        self.allowed_networks = allowed_networks or []

    def session(self):
        connector = aiohttp.TCPConnector(resolver=ValidatingResolver(self.allowed_networks), use_dns_cache=False,
                                        limit=20, ssl=True)
        return aiohttp.ClientSession(connector=connector, trust_env=False,
                                     timeout=aiohttp.ClientTimeout(total=None, connect=10, sock_read=30))

    def check(self, url: str):
        parsed = validate_url(url, self.allowed_hosts)
        # aiohttp skips the resolver for IP literals; validate those here too.
        try:
            ipaddress.ip_address(parsed.hostname)
        except ValueError:
            return parsed
        validate_ips([parsed.hostname], self.allowed_networks)
        return parsed
