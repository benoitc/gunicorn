#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 6.1: Transfer-Encoding codings stack left-to-right;
# chunked must be the final coding. gzip before chunked is valid.
request = {
    "method": "POST",
    "uri": uri("/upload"),
    "version": (1, 1),
    "headers": [
        ("HOST", "example.com"),
        ("TRANSFER-ENCODING", "gzip, chunked"),
    ],
    "body": b"hello",
}
