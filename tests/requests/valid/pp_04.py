#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from gunicorn.config import Config

cfg = Config()
cfg.set("proxy_protocol", True)

request = {
    "method": "GET",
    "uri": uri("/proxy/v2/ipv4"),
    "version": (1, 1),
    "headers": [
        ("HOST", "example.com"),
        ("CONTENT-LENGTH", "0")
    ],
    "body": b""
}
