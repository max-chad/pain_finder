from url_safety import is_public_http_url


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
    ]

    for url in cases:
        assert is_public_http_url(url) is False


def test_public_http_url_rejects_credentials_and_unsupported_schemes():
    assert is_public_http_url("https://user:pass@example.com/reviews") is False
    assert is_public_http_url("file:///etc/passwd") is False
