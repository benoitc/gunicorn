#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 3.2.2 + RFC 3986 section 3.2.2: absolute-form with an
# IP-literal (IPv6) host wrapped in brackets.
request = {
    "method": "GET",
    "uri": uri("http://[::1]:8080/foo"),
    "version": (1, 1),
    "headers": [
        ("HOST", "[::1]:8080"),
    ],
    "body": b"",
}
