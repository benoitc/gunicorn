#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 3.2.3: authority-form with IPv6 literal, used by CONNECT.
request = {
    "method": "CONNECT",
    "uri": uri("[::1]:443"),
    "version": (1, 1),
    "headers": [
        ("HOST", "[::1]:443"),
    ],
    "body": b"",
}
