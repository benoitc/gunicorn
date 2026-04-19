#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9110 section 6.5.1: Transfer-Encoding in trailers alters framing
# and must not be accepted.
from gunicorn.http.errors import InvalidHeaderName
request = InvalidHeaderName
python_only = True
