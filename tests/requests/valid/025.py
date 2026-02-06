#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

request = {
    "method": "POST",
    "uri": uri("/chunked"),
    "version": (1, 1),
    "headers": [
        ('TRANSFER-ENCODING', 'gzip'),
        ('TRANSFER-ENCODING', 'chunked')
    ],
    "body": b"hello world"
}
