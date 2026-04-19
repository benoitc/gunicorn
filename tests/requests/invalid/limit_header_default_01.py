#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from gunicorn.config import Config
from gunicorn.http.errors import LimitRequestHeaders

cfg = Config()
# Setting limit_request_field_size=0 should use default max (8190)
cfg.set('limit_request_field_size', 0)
request = LimitRequestHeaders
