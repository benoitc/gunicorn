#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 3.2.4: asterisk-form ("*") only targets the server itself
# and is only valid with the OPTIONS method. Any other method must be
# rejected as an ill-formed request-line.
from gunicorn.http.errors import InvalidRequestLine
request = InvalidRequestLine
# The C parser (gunicorn_h1c) does not yet enforce this rule.
python_only = True
