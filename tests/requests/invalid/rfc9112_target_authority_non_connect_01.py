#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 3.2.3: authority-form ("host:port") is only valid with
# the CONNECT method. Any other method carrying it must be rejected.
from gunicorn.http.errors import InvalidRequestLine
request = InvalidRequestLine
# The C parser (gunicorn_h1c) does not yet enforce this rule.
python_only = True
