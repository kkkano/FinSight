# -*- coding: utf-8 -*-
from backend.security.ssrf import is_safe_url


def test_is_safe_url_blocks_localhost():
    assert not is_safe_url("http://127.0.0.1/admin")
    assert not is_safe_url("http://localhost/internal")


def test_is_safe_url_blocks_non_http():
    assert not is_safe_url("file:///etc/passwd")


def test_is_safe_url_allows_public_ip():
    assert is_safe_url("https://93.184.216.34/index.html")
