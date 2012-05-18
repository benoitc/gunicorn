from bottle import default_app, route, run

@route('/hello')
def hello():
    return "Hello World!"

app = default_app()
