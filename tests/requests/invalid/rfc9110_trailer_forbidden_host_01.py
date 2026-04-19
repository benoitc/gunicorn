#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9110 section 6.5.1: certain header fields must not be sent in
# trailers because they alter routing or message framing (e.g. Host,
# Content-Length, Transfer-Encoding). Accepting them enables smuggling.
from gunicorn.http.errors import InvalidHeaderName
request = InvalidHeaderName
# The C parser (gunicorn_h1c) does not yet enforce this rule.
python_only = True
