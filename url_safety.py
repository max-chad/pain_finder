from __future__ import annotations

from ipaddress import ip_address
import re
from urllib.parse import urlparse


PRIVATE_HOSTNAMES = {"localhost", "localhost.localdomain", "metadata.google.internal"}
NUMERIC_HOST_RE = re.compile(r"^(?:0[xX][0-9a-fA-F]+|[0-9]+)(?:\.(?:0[xX][0-9a-fA-F]+|[0-9]+))*$")


def is_public_http_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.username or parsed.password:
        return False

    hostname = parsed.hostname
    if not hostname:
        return False
    normalized_host = hostname.rstrip(".").lower()
    if normalized_host in PRIVATE_HOSTNAMES or normalized_host.endswith(".localhost"):
        return False

    try:
        ip = ip_address(normalized_host)
    except ValueError:
        if NUMERIC_HOST_RE.fullmatch(normalized_host):
            return False
        return True
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )
