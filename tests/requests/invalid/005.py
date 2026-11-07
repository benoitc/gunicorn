#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from gunicorn.http.errors import InvalidHeaderName
request = InvalidHeaderName

# gunicorn_h1c reports it as a generic parse error when the read boundary
# falls inside the message (incremental path).
from gunicorn.http.errors import InvalidRequestLine
fast_alternates = (InvalidRequestLine,)
