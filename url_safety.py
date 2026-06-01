from __future__ import annotations

import asyncio
from ipaddress import ip_address
import re
import socket
from urllib.parse import urlparse


PRIVATE_HOSTNAMES = {"localhost", "localhost.localdomain", "metadata.google.internal"}
NUMERIC_HOST_RE = re.compile(r"^(?:0[xX][0-9a-fA-F]+|[0-9]+)(?:\.(?:0[xX][0-9a-fA-F]+|[0-9]+))*$")


def _is_public_ip(value: object) -> bool:
    try:
        ip = ip_address(str(value))
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _normalized_hostname(value: str) -> str | None:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    try:
        parsed.port
    except ValueError:
        return None
    if parsed.username or parsed.password:
        return None

    hostname = parsed.hostname
    if not hostname:
        return None
    normalized_host = hostname.rstrip(".").lower()
    if "%" in normalized_host:
        return None
    if normalized_host in PRIVATE_HOSTNAMES or normalized_host.endswith(".localhost"):
        return None
    if NUMERIC_HOST_RE.fullmatch(normalized_host):
        try:
            ip_address(normalized_host)
        except ValueError:
            return None
    return normalized_host


def is_public_http_url(value: str) -> bool:
    normalized_host = _normalized_hostname(value)
    if not normalized_host:
        return False

    try:
        ip = ip_address(normalized_host)
    except ValueError:
        return True
    return _is_public_ip(ip)


async def is_resolved_public_http_url(value: str) -> bool:
    if not is_public_http_url(value):
        return False

    parsed = urlparse(value.strip())
    normalized_host = _normalized_hostname(value)
    if not normalized_host:
        return False

    try:
        ip_address(normalized_host)
    except ValueError:
        pass
    else:
        return True

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return False

    loop = asyncio.get_running_loop()
    try:
        records = await loop.getaddrinfo(normalized_host, port, type=socket.SOCK_STREAM)
    except OSError:
        return False

    resolved_ips = {record[4][0] for record in records if record and len(record) >= 5 and record[4]}
    return bool(resolved_ips) and all(_is_public_ip(address) for address in resolved_ips)
