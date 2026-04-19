#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 3.2.2: absolute-form with https scheme (proxy requests).
request = {
    "method": "GET",
    "uri": uri("https://example.com/foo"),
    "version": (1, 1),
    "headers": [
        ("HOST", "example.com"),
    ],
    "body": b"",
}
