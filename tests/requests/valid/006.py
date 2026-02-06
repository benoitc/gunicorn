#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

request = {
    "method": "GET",
    "uri": uri("/get_no_headers_no_body/world"),
    "version": (1, 1),
    "headers": [],
    "body": b""
}
