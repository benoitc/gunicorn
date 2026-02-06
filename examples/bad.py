#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import tempfile
files = []
def app(environ, start_response):
    files.append(tempfile.mkstemp())
    start_response('200 OK', [('Content-type', 'text/plain'), ('Content-length', '2')])
    return ['ok']
