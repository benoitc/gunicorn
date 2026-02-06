#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import cherrypy


class Root:
    @cherrypy.expose
    def index(self):
        return 'Hello World!'

cherrypy.config.update({'environment': 'embedded'})

app = cherrypy.tree.mount(Root())
