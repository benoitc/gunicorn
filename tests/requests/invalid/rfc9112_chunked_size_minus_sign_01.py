#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 7.1: chunk-size = 1*HEXDIG; negative sign is invalid.
from gunicorn.http.errors import InvalidChunkSize
request = InvalidChunkSize
