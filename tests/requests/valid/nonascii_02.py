#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

request = {
    "method": "PUT",
    # intentionally expressive - suffix to be stripped once treq.py:uri() is refactored
    "uri": uri("/\N{LATIN SMALL LETTER Y WITH DIAERESIS}/french..?\N{LATIN SMALL LETTER E WITH ACUTE}=\N{LATIN SMALL LETTER E WITH GRAVE}".encode().decode("latin-1")),
    "version": (1, 1),
    "headers": [
        ("UNICODE", "awesome"),
        ("CONTENT-LENGTH", "6"),
    ],
    "body": "\N{LATIN CAPITAL LETTER A WITH GRAVE}\N{LATIN CAPITAL LETTER A WITH ACUTE}\N{LATIN CAPITAL LETTER A WITH CIRCUMFLEX}".encode()
}
