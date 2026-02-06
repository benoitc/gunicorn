#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from gunicorn.config import Config
from gunicorn.http.errors import InvalidHTTPVersion

cfg = Config()
request = InvalidHTTPVersion
