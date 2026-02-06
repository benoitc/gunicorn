#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

request = {
    "method": "GET",
    "uri": uri('/with_"quotes"?foo="bar"'),
    "version": (1, 1),
    "headers": [],
    "body": b""
}
