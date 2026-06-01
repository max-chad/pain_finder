import socket

from url_safety import is_public_http_url, is_resolved_public_http_url


def test_public_http_url_accepts_public_hosts():
    assert is_public_http_url("https://example.com/reviews") is True
    assert is_public_http_url("http://8.8.8.8/reviews") is True


def test_public_http_url_rejects_private_and_ambiguous_numeric_hosts():
    cases = [
        "http://localhost/reviews",
        "http://127.0.0.1/reviews",
        "http://10.0.0.1/reviews",
        "http://[::1]/reviews",
        "http://2130706433/reviews",
        "http://0177.0.0.1/reviews",
        "http://0x7f.0.0.1/reviews",
        "http://%31%32%37.0.0.1/reviews",
        "http://[fe80::1%25eth0]/reviews",
    ]

    for url in cases:
        assert is_public_http_url(url) is False


def test_public_http_url_rejects_credentials_and_unsupported_schemes():
    assert is_public_http_url("https://user:pass@example.com/reviews") is False
    assert is_public_http_url("file:///etc/passwd") is False
    assert is_public_http_url("https://example.com:bad/reviews") is False


async def test_resolved_public_http_url_rejects_domains_that_resolve_private(monkeypatch):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.10", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    assert await is_resolved_public_http_url("https://reviews.example.test/path") is False


async def test_resolved_public_http_url_accepts_domains_that_resolve_public(monkeypatch):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    assert await is_resolved_public_http_url("https://reviews.example.test/path") is True
