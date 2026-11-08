#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 3.2 / RFC 3986 section 2: a request-target is printable
# ASCII; other bytes must be percent-encoded.
from gunicorn.http.errors import InvalidRequestLine
request = InvalidRequestLine
