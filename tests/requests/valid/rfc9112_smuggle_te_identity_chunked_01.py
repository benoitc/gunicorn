#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 6.1: identity is a no-op coding and may precede chunked.
# Worth codifying because proxies have historically disagreed on this form.
request = {
    "method": "POST",
    "uri": uri("/upload"),
    "version": (1, 1),
    "headers": [
        ("HOST", "example.com"),
        ("TRANSFER-ENCODING", "identity, chunked"),
    ],
    "body": b"hello",
}
