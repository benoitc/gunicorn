# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from gunicorn.workers.ggevent import BASE_WSGI_ENV, GeventBaseWorker 
from gevent import wsgi


class WSGIHandler(wsgi.WSGIHandler):
    def log_request(self, *args):
        pass

    def prepare_env(self):
        env = super(WSGIHandler, self).prepare_env()
        env['RAW_URI'] = self.request.uri
        return env
        
        
class WSGIServer(wsgi.WSGIServer):
    base_env = BASE_WSGI_ENV  

class GeventWSGIWorker(GeventBaseWorker):
    "The Gevent StreamServer based workers."
    server_class = WSGIServer
    wsgi_handler = WSGIHandler
