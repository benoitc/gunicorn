#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 2.2: one empty line before the request line is ignored.
request = {
    "method": "GET",
    "uri": uri("/leading"),
    "version": (1, 1),
    "headers": [("HOST", "a")],
    "body": b""
}
