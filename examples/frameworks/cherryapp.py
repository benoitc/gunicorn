import cherrypy


class Root:
    @cherrypy.expose
    def index(self):
        return 'Hello World!'

cherrypy.config.update({'environment': 'embedded'})

app = cherrypy.tree.mount(Root())
