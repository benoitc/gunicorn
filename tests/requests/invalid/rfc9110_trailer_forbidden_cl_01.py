#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9110 section 6.5.1: Content-Length in trailers is a classic
# smuggling vector; origin must reject.
from gunicorn.http.errors import InvalidHeaderName
request = InvalidHeaderName
python_only = True
