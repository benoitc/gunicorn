#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9110 section 5.5: field-value characters are field-vchar (VCHAR +
# obs-text) plus SP/HTAB. Control characters other than HTAB must not
# appear, to prevent log/response injection and parser confusion.
from gunicorn.http.errors import InvalidHeader
request = InvalidHeader
python_only = True
