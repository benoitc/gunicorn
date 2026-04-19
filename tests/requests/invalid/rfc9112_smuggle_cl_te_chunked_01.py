#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 6.1: a message with both Content-Length and
# Transfer-Encoding: chunked is the classic CL.TE desync vector and MUST
# be rejected by the origin server. PortSwigger HTTP Desync corpus, CL.TE.
from gunicorn.http.errors import InvalidHeader
request = InvalidHeader
