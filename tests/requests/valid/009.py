#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

request = {
    "method": "POST",
    "uri": uri("/post_identity_body_world?q=search#hey"),
    "version": (1, 1),
    "headers": [
        ("ACCEPT", "*/*"),
        ("TRANSFER-ENCODING", "identity"),
        ("CONTENT-LENGTH", "5")
    ],
    "body": b"World"
}
