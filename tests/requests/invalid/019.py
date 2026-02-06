#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from gunicorn.config import Config
from gunicorn.http.errors import InvalidSchemeHeaders

request = InvalidSchemeHeaders
cfg = Config()
cfg.set('forwarded_allow_ips', '*')
