#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 7.1: chunk-size is 1*HEXDIG. Leading zeros are permitted
# but have been used in smuggling vectors; fixture pins accepted behavior.
request = {
    "method": "POST",
    "uri": uri("/upload"),
    "version": (1, 1),
    "headers": [
        ("HOST", "example.com"),
        ("TRANSFER-ENCODING", "chunked"),
    ],
    "body": b"hello",
}
