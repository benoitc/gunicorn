#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 request-target / RFC 3986: a request-target is a URI-reference
# and must not contain a raw NUL. Recipients should respond with 400.
from gunicorn.http.errors import InvalidRequestLine
request = InvalidRequestLine
