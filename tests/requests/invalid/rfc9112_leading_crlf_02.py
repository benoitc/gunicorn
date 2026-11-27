#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 2.2: only one empty line before the request line is
# ignored; a second one is an empty request line.
from gunicorn.http.errors import InvalidRequestLine
request = InvalidRequestLine
