#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 7.1: chunk-size = 1*HEXDIG, which allows both cases.
request = {
    "method": "POST",
    "uri": uri("/upload"),
    "version": (1, 1),
    "headers": [
        ("HOST", "example.com"),
        ("TRANSFER-ENCODING", "chunked"),
    ],
    "body": b"0123456789",
}
