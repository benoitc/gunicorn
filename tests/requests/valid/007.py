#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

request = {
    "method": "GET",
    "uri": uri("/get_one_header_no_body"),
    "version": (1, 1),
    "headers": [
        ("ACCEPT", "*/*")
    ],
    "body": b""
}
