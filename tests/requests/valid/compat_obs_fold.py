#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from gunicorn.http.errors import ObsoleteFolding
from gunicorn.config import Config

cfg = Config()
cfg.set('permit_obsolete_folding', True)

request = {
    "method": "GET",
    "uri": uri("/"),
    "version": (1, 1),
    "headers": [
        ("LONG", "one two"),
        ("HOST", "localhost"),
    ],
    "body": b""
}
