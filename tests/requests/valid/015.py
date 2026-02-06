#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

request = {
    "method": "GET",
    "uri": uri("/test"),
    "version": (1, 0),
    "headers": [
        ("HOST", "0.0.0.0:5000"),
        ("USER-AGENT", "ApacheBench/2.3"),
        ("ACCEPT", "*/*")
    ],
    "body": b""
}
