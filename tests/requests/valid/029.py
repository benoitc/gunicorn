#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from gunicorn.config import Config

cfg = Config()

request = {
    "method": "GET",
    "uri": uri("/stuff/here?foo=bar"),
    "version": (1, 1),
    "headers": [
        ('TRANSFER-ENCODING', 'identity'),
        ('TRANSFER-ENCODING', 'chunked'),
    ],
    "body": b"hello"
}
