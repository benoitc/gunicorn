# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import logging
import os
import re
import StringIO
import sys
from urllib import unquote

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
        self.response_headers = []
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
        
        if self.parser.headers_dict.get('Expect','').lower() == "100-continue":
            self.socket.send("100 Continue\n")
            
        if not self.parser.content_len and not self.parser.is_chunked:
            wsgi_input = StringIO.StringIO()
        else:
            wsgi_input = TeeInput(self.socket, self.parser, buf[i:])
                
        # This value should evaluate true if an equivalent application
        # object may be simultaneously invoked by another process, and
        # should evaluate false otherwise. In debug mode we fall to one
        # worker so we comply to pylons and other paster app.
        wsgi_multiprocess = (self.debug == False)

        # authors should be aware that REMOTE_HOST and REMOTE_ADDR
        # may not qualify the remote addr:
        # http://www.ietf.org/rfc/rfc3875
        client_address = self.client_address or "127.0.0.1"
        forward_adress = self.parser.headers_dict.get('X-Forwarded-For', 
                                                client_address)
        
        if isinstance(forward_adress, basestring):
            # we only took the last one
            # http://en.wikipedia.org/wiki/X-Forwarded-For
            if "," in forward_adress:
                forward_adress = forward_adress.split(",")[-1].strip()
            remote_addr = forward_adress.split(":")
            if len(remote_addr) == 1:
                remote_addr.append('')
        else:
            remote_addr = forward_adress
                
        # Try to server address from headers
        server_address = self.parser.headers_dict.get('Host', 
                                                    self.server_address)
        if isinstance(server_address, basestring):
            server_address =  server_address.split(":")
            if len(server_address) == 1:
                server_address.append('')
                
        script_name = self.parser.headers_dict.get("SCRIPT_NAME", 
                                            os.environ.get("SCRIPT_NAME", ""))
        path_info = self.parser.path
        if script_name:
            path_info = path_info.split(script_name, 1)[-1]

        environ = {
            "wsgi.url_scheme": 'http',
            "wsgi.input": wsgi_input,
            "wsgi.errors": sys.stderr,
            "wsgi.version": (1, 0),
            "wsgi.multithread": False,
            "wsgi.multiprocess": wsgi_multiprocess,
            "wsgi.run_once": False,
            "SCRIPT_NAME": script_name,
            "SERVER_SOFTWARE": self.SERVER_VERSION,
            "REQUEST_METHOD": self.parser.method,
            "PATH_INFO": unquote(path_info),
            "QUERY_STRING": self.parser.query_string,
            "RAW_URI": self.parser.raw_path,
            "CONTENT_TYPE": self.parser.headers_dict.get('Content-Type', ''),
            "CONTENT_LENGTH": str(wsgi_input.len),
            "REMOTE_ADDR": remote_addr[0],
            "REMOTE_PORT": str(remote_addr[1]),
            "SERVER_NAME": server_address[0],
            "SERVER_PORT": str(server_address[1]),
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
            self.response_headers.append((name, value.strip()))     
        self.start_response_called = True
