#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from gunicorn.config import Config

cfg = Config()
cfg.set("strip_header_spaces", True)

request = {
    "method": "GET",
    "uri": uri("/stuff/here?foo=bar"),
    "version": (1, 1),
    "headers": [
        ("CONTENT-LENGTH", "3"),
    ],
    "body": b"xyz"
}