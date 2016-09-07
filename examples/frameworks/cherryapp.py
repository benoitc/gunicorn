import cherrypy

cherrypy.config.update({'environment': 'embedded'})

class Root(object):
    @cherrypy.expose
    def index(self):
        return 'Hello World!'
    index.exposed = True

app = cherrypy.Application(Root(), script_name=None, config=None)