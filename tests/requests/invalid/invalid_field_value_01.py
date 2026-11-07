#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from gunicorn.config import Config
from gunicorn.http.errors import InvalidHeader

cfg = Config()
request = InvalidHeader

# gunicorn_h1c reports it as a generic parse error when the read boundary
# falls inside the message (incremental path).
from gunicorn.http.errors import InvalidRequestLine
fast_alternates = (InvalidRequestLine,)
