# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from __future__ import with_statement
from gunicorn.worker.ggevent import *
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
