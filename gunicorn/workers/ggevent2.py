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
from gevent import wsgi

import gunicorn
from gunicorn.workers.base import Worker

class WSGIHandler(wsgi.WSGIHandler):
    def log_request(self, *args):
        pass

class GEvent2Worker(Worker):
    
    base_env = {
        'GATEWAY_INTERFACE': 'CGI/1.1',
        'SERVER_SOFTWARE': 'gevent/%s gunicorn/%s' % (gevent.__version__,
                                                    gunicorn.__version__),
        'SCRIPT_NAME': '',
        'wsgi.version': (1, 0),
        'wsgi.url_scheme': 'http',
        'wsgi.multithread': False,
        'wsgi.multiprocess': True,
        'wsgi.run_once': False
    }
    
    def __init__(self, *args, **kwargs):
        super(GEvent2Worker, self).__init__(*args, **kwargs)
        self.worker_connections = self.cfg.worker_connections
        self.pool = None
    
    @classmethod
    def setup(cls):
        from gevent import monkey
        monkey.patch_all(dns=False)
   
    def handle_request(self, req):
        self.pool.spawn(self.handle, req)
       
    def handle(self, req):
        handle = WSGIHandler(req)
        handle.handle(self)
        
    def run(self):
        self.socket.setblocking(1)
        env = self.base_env.copy()
        
        env.update({
            'SERVER_NAME': self.address[0],
            'SERVER_PORT': str(self.address[1]) 
        })
        self.base_env = env
        
        http = core.http()
        http.set_gencb(self.handle_request)
        self.pool = Pool(self.worker_connections)
        
        self.application = self.wsgi
        acceptor = gevent.spawn(http.accept, self.socket.fileno())
        
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


        
        
        
