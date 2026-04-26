import pytest

from gunicorn.config import Config
from gunicorn.http.parser import RequestParser


REQUEST = (
    b"GET /admin/environ HTTP/1.1\r\n"
    b"Host: localhost\r\n"
    b"SCRIPT_NAME: /admin\r\n"
    b"\r\n"
)


def parse_request(http_parser, peer_addr):
    cfg = Config()
    cfg.set("http_parser", http_parser)
    cfg.set("forwarded_allow_ips", "10.0.0.1")
    cfg.set("forwarder_headers", "SCRIPT_NAME,PATH_INFO")
    return next(iter(RequestParser(cfg, [REQUEST], peer_addr)))


@pytest.mark.parametrize(
    ("peer_addr", "expected_headers"),
    [
        (("127.0.0.1", 12345), [("HOST", "localhost")]),
        (("10.0.0.1", 12345), [("HOST", "localhost"), ("SCRIPT_NAME", "/admin")]),
    ],
)
def test_forwarder_headers_respect_forwarded_allow_ips(
    http_parser, peer_addr, expected_headers
):
    req = parse_request(http_parser, peer_addr)
    assert req.headers == expected_headers
