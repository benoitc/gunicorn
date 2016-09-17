import cherrypy

cherrypy.config.update({'environment': 'embedded'})

class Root(object):
    @cherrypy.expose
    def index(self):
        return 'Hello World!'

cherrypy.config.update({'engine.autoreload.on': False})
cherrypy.server.unsubscribe()
cherrypy.engine.start()
app = cherrypy.tree.mount(Root())

