# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import re
import StringIO
import sys
from urllib import unquote
import logging

from gunicorn import __version__
from gunicorn.http.parser import Parser
from gunicorn.http.tee import TeeInput
from gunicorn.util import CHUNK_SIZE, read_partial, normalize_name

NORMALIZE_SPACE = re.compile(r'(?:\r\n)?[ \t]+')

class RequestError(Exception):
    pass
        
class Request(object):
    
    SERVER_VERSION = "gunicorn/%s" % __version__
    
    DEFAULTS = {
        "wsgi.url_scheme": 'http',
        "wsgi.input": StringIO.StringIO(),
        "wsgi.errors": sys.stderr,
        "wsgi.version": (1, 0),
        "wsgi.multithread": False,
        "wsgi.multiprocess": True,
        "wsgi.run_once": False,
        "SCRIPT_NAME": "",
        "SERVER_SOFTWARE": "gunicorn/%s" % __version__
    }

    def __init__(self, socket, client_address, server_address, debug=False):
        self.debug = debug
        self.socket = socket
    
        self.client_address = client_address
        self.server_address = server_address
        self.response_status = None
        self.response_headers = {}
        self._version = 11
        self.parser = Parser()
        self.start_response_called = False
        self.log = logging.getLogger(__name__)

    def read(self):
        environ = {}
        headers = []
        buf = ""
        buf = read_partial(self.socket, CHUNK_SIZE)
        i = self.parser.filter_headers(headers, buf)
        if i == -1 and buf:
            while True:
                data = read_partial(self.socket, CHUNK_SIZE)
                if not data: break
                buf += data
                i = self.parser.filter_headers(headers, buf)
                if i != -1: break

        self.log.debug("%s", self.parser.status)
        self.log.debug("Headers:\n%s" % headers)
        
        if self.parser.headers_dict.get('Expect', '').lower() == "100-continue":
            self.socket.send("100 Continue\n")
            
        if not self.parser.content_len and not self.parser.is_chunked:
            wsgi_input = StringIO.StringIO()
        else:
            wsgi_input = TeeInput(self.socket, self.parser, buf[i:])
                
                
        if self.debug:
            # This value should evaluate true if an equivalent application
            # object may be simultaneously invoked by another process, and
            # should evaluate false otherwise. In debug mode we fall to one
            # worker so we comply to pylons and other paster app.
            wsgi_multiprocess = False
        else:
            wsgi_multiprocess = True
            
            

        
        # authors should be aware that REMOTE_HOST and REMOTE_ADDR
        # may not qualify the remote addr:
        # http://www.ietf.org/rfc/rfc3875
        try:
            if 'X-Forwarded-For' in self.parser.headers_dict:
                forward_adress = self.parser.headers_dict.get('X-Forwarded-For')
                
                # we only took the last one
                # http://en.wikipedia.org/wiki/X-Forwarded-For
                if "," in forward_adress:
                    forward_adress = forward_adress.split(",")[-1].strip()
                
                if ":" in forward_adress:
                    remote_addr, remote_port = forward_adress.split(':')
                else:
                    remote_addr, remote_port = (forward_adress, '')
            elif self.client_address is not None:
                remote_addr, remote_port = self.client_address
            else:  
                remote_addr, remote_port = ('127.0.0.1', '')
        except:
             remote_addr, remote_port = ('127.0.0.1', '')
            
        
        # Try to server address from headers
        if 'Host' in self.parser.headers_dict:
            server_address = self.parser.headers_dict.get('Host')
        else:
            server_address = self.server_address
            
        if isinstance(server_address, basestring):
            if ':' in server_address:
                server_name, server_port = server_address.split(":")
            else:
                server_name = server_address
                server_port = ''
        else:
            server_name, server_port = server_address
        
        environ = {
            "wsgi.url_scheme": 'http',
            "wsgi.input": wsgi_input,
            "wsgi.errors": sys.stderr,
            "wsgi.version": (1, 0),
            "wsgi.multithread": False,
            "wsgi.multiprocess": wsgi_multiprocess,
            "wsgi.run_once": False,
            "SCRIPT_NAME": "",
            "SERVER_SOFTWARE": self.SERVER_VERSION,
            "REQUEST_METHOD": self.parser.method,
            "PATH_INFO": unquote(self.parser.path),
            "QUERY_STRING": self.parser.query_string,
            "RAW_URI": self.parser.raw_path,
            "CONTENT_TYPE": self.parser.headers_dict.get('Content-Type', ''),
            "CONTENT_LENGTH": str(wsgi_input.len),
            "REMOTE_ADDR": remote_addr,
            "REMOTE_PORT": remote_port,
            "SERVER_NAME": server_name,
            "SERVER_PORT": server_port,
            "SERVER_PROTOCOL": self.parser.raw_version
        }
        
        for key, value in self.parser.headers:
            key = 'HTTP_' + key.upper().replace('-', '_')
            if key not in ('HTTP_CONTENT_TYPE', 'HTTP_CONTENT_LENGTH'):
                environ[key] = value
        return environ
        
    def start_response(self, status, response_headers, exc_info=None):
        if exc_info:
            try:
                if self.start_response_called:
                    raise exc_info[0], exc_info[1], exc_info[2]
            finally:
                exc_info = None
        elif self.start_response_called:
            raise AssertionError("Response headers already set!")

        self.response_status = status
        for name, value in response_headers:
            name = normalize_name(name)
            if not isinstance(value, basestring):
                value = str(value)
            self.response_headers[name] = value.strip()        
        self.start_response_called = True
