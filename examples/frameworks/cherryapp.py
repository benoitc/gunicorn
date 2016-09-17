import cherrypy

class Root(object):
    @cherrypy.expose
    def index(self):
        return 'Hello World!'

app = cherrypy.tree.mount(Root())
