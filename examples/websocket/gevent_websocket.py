# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.
#
# Example code from Eventlet sources

import gevent

from base_websocket import BaseWebSocketWSGI as WebSocketWSGI

# demo app
import os
import random
def handle(ws):
    """  This is the websocket handler function.  Note that we 
    can dispatch based on path in here, too."""
    if ws.path == '/echo':
        while True:
            m = ws.wait()
            if m is None:
                break
            ws.send(m)
            
    elif ws.path == '/data':
        for i in xrange(10000):
            ws.send("0 %s %s\n" % (i, random.random()))
            gevent.sleep(0.1)
                            
wsapp = WebSocketWSGI(handle)
def app(environ, start_response):
    """ This resolves to the web page or the websocket depending on
    the path."""
    if environ['PATH_INFO'] == '/' or environ['PATH_INFO'] == "":
        data = open(os.path.join(
                     os.path.dirname(__file__), 
                     'websocket.html')).read()
        data = data % environ
        start_response('200 OK', [('Content-Type', 'text/html'),
                                 ('Content-Length', len(data))])
        return [data]
    else:
        return wsapp(environ, start_response)
