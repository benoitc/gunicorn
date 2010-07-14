# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import os

import gevent
from gevent import core
from gevent import monkey
monkey.noisy = False
from gevent.pool import Pool
from gevent import pywsgi

import gunicorn
from gunicorn.workers.base import Worker

class WSGIHandler(pywsgi.WSGIHandler):
    def log_request(self, *args):
        pass


class WSGIServer(pywsgi.WSGIServer):
    base_env = {'GATEWAY_INTERFACE': 'CGI/1.1',
                'SERVER_SOFTWARE': 'gevent/%s gunicorn/%s' % (gevent.__version__,
                                                            gunicorn.__version__),
                'SCRIPT_NAME': '',
                'wsgi.version': (1, 0),
                'wsgi.multithread': False,
                'wsgi.multiprocess': False,
                'wsgi.run_once': False}

        
    
class GEvent2Worker(Worker):

    
    def __init__(self, *args, **kwargs):
        super(GEvent2Worker, self).__init__(*args, **kwargs)
        self.worker_connections = self.cfg.worker_connections
    
    @classmethod
    def setup(cls):
        from gevent import monkey
        monkey.patch_all(dns=False)
        
    def run(self):
        self.socket.setblocking(1)
        pool = Pool(self.worker_connections)
        
        server = WSGIServer(self.socket, application=self.wsgi, 
                        spawn=pool, handler_class=WSGIHandler)
        
        acceptor = gevent.spawn(server.serve_forever)
        
        try:
            while self.alive:
                self.notify()
            
                if self.ppid != os.getppid():
                    self.log.info("Parent changed, shutting down: %s" % self)
                    gevent.kill(acceptor)
                    break
                gevent.sleep(0.1)            
            self.pool.join(timeout=self.timeout)
        except KeyboardInterrupt:
            pass


        
        
        
