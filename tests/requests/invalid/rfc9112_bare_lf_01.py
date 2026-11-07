#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 2.2: a bare LF is not a line terminator here; every
# parser (WSGI, ASGI and gunicorn_h1c >= 0.6.10) rejects it.
from gunicorn.http.errors import InvalidHeader, InvalidRequestLine
request = InvalidHeader
# gunicorn_h1c reports it as a generic parse error on the incremental path.
fast_alternates = (InvalidRequestLine,)
