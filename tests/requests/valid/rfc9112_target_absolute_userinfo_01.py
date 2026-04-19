#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 3.2.2: absolute-form with userinfo and explicit port.
request = {
    "method": "GET",
    "uri": uri("http://user:pass@example.com:8080/foo?q=1"),
    "version": (1, 1),
    "headers": [
        ("HOST", "example.com:8080"),
    ],
    "body": b"",
}
