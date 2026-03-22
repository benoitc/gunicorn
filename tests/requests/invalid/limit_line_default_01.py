#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from gunicorn.config import Config
from gunicorn.http.errors import LimitRequestLine

cfg = Config()
# Setting limit_request_line=0 should use default max (8190)
cfg.set('limit_request_line', 0)
request = LimitRequestLine
