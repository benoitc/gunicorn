#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

request = {
    "method": "PUT",
    # intentionally expressive - suffix to be stripped once treq.py:uri() is refactored
    "uri": uri("/\N{LATIN SMALL LETTER SHARP S}/germans..?\N{LATIN SMALL LETTER O WITH DIAERESIS}=\N{LATIN SMALL LETTER A WITH DIAERESIS}".encode().decode("latin-1")),
    "version": (1, 1),
    "headers": [
        ("UNICODE", "awesome"),
        ("CONTENT-LENGTH", "6"),
    ],
    "body": "\N{LATIN CAPITAL LETTER A WITH DIAERESIS}\N{LATIN CAPITAL LETTER O WITH DIAERESIS}\N{LATIN CAPITAL LETTER U WITH DIAERESIS}".encode()
}
