import cherrypy

cherrypy.config.update({'environment': 'embedded'})

class Root(object):
    @cherrypy.expose
    def index(self):
        return 'Hello World!'

app = cherrypy.tree.mount(Root())
cherrypy.server.unsubscribe()
cherrypy.engine.start()
app = cherrypy.tree.mount(Root())
