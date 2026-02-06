#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from gunicorn.config import Config

cfg = Config()
cfg.set("permit_unconventional_http_method", True)

request = {
    "method": "-blargh",
    "uri": uri("/foo"),
    "version": (1, 1),
    "headers": [],
    "body": b""
}
