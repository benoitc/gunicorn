#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from gunicorn.http.errors import InvalidHeaderName
from gunicorn.config import Config

cfg = Config()
cfg.set("header_map", "refuse")

request = InvalidHeaderName
