#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# RFC 9112 section 3.2.4: asterisk-form, only valid with OPTIONS.
request = {
    "method": "OPTIONS",
    "uri": uri("*"),
    "version": (1, 1),
    "headers": [
        ("HOST", "example.com"),
    ],
    "body": b"",
}
