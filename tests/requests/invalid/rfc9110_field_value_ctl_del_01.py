#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9110 section 5.5: DEL (0x7F) is a control character and not a VCHAR;
# it must not appear in a field-value.
from gunicorn.http.errors import InvalidHeader
request = InvalidHeader
python_only = True
