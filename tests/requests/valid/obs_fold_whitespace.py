#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from gunicorn.http.errors import ObsoleteFolding
from gunicorn.config import Config

cfg = Config()
cfg.set('permit_obsolete_folding', True)

req1 = {
    "method": "POST",
    "uri": uri("/1"),
    "version": (1, 1),
    "headers": [
        ("HOST", "example.com"),
        ("CONNECTION", "keep-alive "),
        ("CONTENT-LENGTH", "3"),
    ],
    "body": b"123",
}

req2 = {
    "method": "POST",
    "uri": uri("/2"),
    "version": (1, 1),
    "headers": [
        ("HOST", "example.com"),
        ("CONNECTION", "close "),
        ("TRANSFER-ENCODING", "chunked"),
    ],
    "trailers": [
        ("TRAILER-CHECKSUM", "0"),
    ],
    "body": b"123",
}

request = [req1, req2]
