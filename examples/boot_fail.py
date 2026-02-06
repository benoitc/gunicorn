#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

raise RuntimeError("Bad app!")

def app(environ, start_response):
    assert 1 == 2, "Shouldn't get here."
