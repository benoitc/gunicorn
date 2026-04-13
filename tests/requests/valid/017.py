#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

request = {
    "method": "GET",
    "uri": uri("/stuff/here?foo=bar"),
    "version": (1, 0),
    "headers": [
        ("IF-MATCH", "bazinga!"),
        ("IF-MATCH", "large-sound")
    ],
    "body": b""
}
