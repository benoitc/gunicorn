# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from datetime import datetime

from gunicorn.workers.ggevent import BASE_WSGI_ENV, GeventWorker 
from gevent import wsgi


class WSGIHandler(wsgi.WSGIHandler):

    @property
    def status(self):
        return ' '.join([str(self.code), self.reason])

    def log_request(self, length):
        self.response_length = length
        response_time = datetime.now() - self.time_start
        self.server.log.access(self, self.environ, response_time)

    def prepare_env(self):
        env = super(WSGIHandler, self).prepare_env()
        env['RAW_URI'] = self.request.uri
        self.environ = env
        return env

    def handle(self):
        self.time_start = datetime.now()
        super(WSGIHandler, self).handle()

        
class WSGIServer(wsgi.WSGIServer):
    base_env = BASE_WSGI_ENV  

class GeventWSGIWorker(GeventWorker):
    "The Gevent StreamServer based workers."
    server_class = WSGIServer
    wsgi_handler = WSGIHandler
