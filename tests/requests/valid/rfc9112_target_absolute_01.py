#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 3.2.2: absolute-form request-target.
request = {
    "method": "GET",
    "uri": uri("http://example.com/foo?q=1"),
    "version": (1, 1),
    "headers": [
        ("HOST", "example.com"),
    ],
    "body": b"",
}
