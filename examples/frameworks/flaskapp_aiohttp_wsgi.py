# Example command to run the example:
#
#   $ gunicorn flaskapp_aiohttp_wsgi:aioapp -k aiohttp.worker.GunicornWebWorker
#

from aiohttp import web
from aiohttp_wsgi import WSGIHandler
from flask import Flask

app = Flask(__name__)


@app.route('/')
def hello():
    return 'Hello, world!'


def make_aiohttp_app(app):
    wsgi_handler = WSGIHandler(app)
    aioapp = web.Application()
    aioapp.router.add_route('*', '/{path_info:.*}', wsgi_handler)
    return aioapp

aioapp = make_aiohttp_app(app)
