#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 6.3: a request whose Transfer-Encoding does not end with
# chunked MUST get 400.
from gunicorn.http.errors import InvalidHeader
request = InvalidHeader
