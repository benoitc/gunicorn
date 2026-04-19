#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 3.2: request-target must be one of origin-form,
# absolute-form, authority-form, or asterisk-form. A relative reference
# like "foo/bar" matches none of these and must be rejected.
from gunicorn.http.errors import InvalidRequestLine
request = InvalidRequestLine
# The C parser (gunicorn_h1c) does not yet enforce this rule.
python_only = True
