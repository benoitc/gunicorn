#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# Raw UTF-8 in the request-target (was valid/027). RFC 9112 section 3.2 /
# RFC 3986 section 2: it must be percent-encoded, so this is a 400.
from gunicorn.http.errors import InvalidRequestLine
request = InvalidRequestLine
