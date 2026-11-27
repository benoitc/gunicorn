#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 6.3: Transfer-Encoding does not end with chunked, so the
# body length cannot be determined; identity is no longer a transfer coding.
from gunicorn.http.errors import InvalidHeader
request = InvalidHeader
