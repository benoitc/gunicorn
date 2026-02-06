#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

request = {
    "method": "POST",
    "uri": uri("/two_chunks_mult_zero_end"),
    "version": (1, 1),
    "headers": [
        ("TRANSFER-ENCODING", "chunked")
    ],
    "body": b"hello world"
}
