#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 3.2.3: authority-form, only valid with CONNECT.
request = {
    "method": "CONNECT",
    "uri": uri("example.com:443"),
    "version": (1, 1),
    "headers": [
        ("HOST", "example.com:443"),
    ],
    "body": b"",
}
