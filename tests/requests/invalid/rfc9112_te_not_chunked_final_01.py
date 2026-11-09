#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 6.3: a request whose Transfer-Encoding does not end with
# chunked MUST get 400.
from gunicorn.http.errors import InvalidHeader
request = InvalidHeader
# gunicorn_h1c 0.6.13 frames this body as empty instead of rejecting it;
# gunicorn rejects it after parsing (CallbackRequest.from_parser), which
# tests/test_transfer_encoding.py covers through the ASGI worker.
python_only = True
