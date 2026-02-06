#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

request = {
    "method": "GET",
    "uri": uri("/first"),
    "version": (1, 1),
    "headers": [("CONNECTION", "Close")],
    "body": b""
}
