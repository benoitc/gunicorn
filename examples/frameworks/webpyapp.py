#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# Run with
#
# $ gunicorn webpyapp:app
#

import web

urls = (
    '/', 'index'
)

class index:
    def GET(self):
        return "Hello, world!"

app = web.application(urls, globals()).wsgifunc()
