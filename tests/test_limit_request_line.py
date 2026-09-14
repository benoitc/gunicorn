#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import unittest

from gunicorn.config import Config
from gunicorn.http.errors import LimitRequestLine
from gunicorn.http.message import Request
from gunicorn.http.unreader import IterUnreader


def _parse(limit, reqline):
    cfg = Config()
    cfg.set("limit_request_line", limit)
    cfg.set("http_parser", "python")
    data = reqline + b"\r\nHost: example\r\n\r\n"
    return Request(cfg, IterUnreader([data]), ("127.0.0.1", 80))


def _line(n):
    prefix = b"GET /"
    suffix = b" HTTP/1.1"
    pad = n - len(prefix) - len(suffix)
    assert pad > 0
    return prefix + (b"a" * pad) + suffix


class LimitRequestLineTests(unittest.TestCase):
    def test_limit_above_8190_is_honored(self):
        line = _line(8194)
        req = _parse(8200, line)
        self.assertEqual(req.limit_request_line, 8200)
        self.assertEqual(req.method, "GET")

    def test_limit_above_8190_still_rejects_oversize_line(self):
        with self.assertRaises(LimitRequestLine):
            _parse(8200, _line(8201))

    def test_default_size_still_rejects_8194_byte_line(self):
        with self.assertRaises(LimitRequestLine):
            _parse(4094, _line(8194))


if __name__ == "__main__":
    unittest.main()
