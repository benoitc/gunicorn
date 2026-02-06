#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.


request = {
    "method": "GET",
    "uri": uri("/"),
    "version": (1, 1),
    "headers": [
        ("HOST", "localhost"),
        ("NAME", "value")
    ],
    "body": b"",
}
