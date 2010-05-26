# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import errno
import logging
import os
import re
import socket

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO
    
import sys
from urllib import unquote

from gunicorn import __version__
from gunicorn.http.parser import Parser
from gunicorn.http.response import Response, KeepAliveResponse
from gunicorn.http.tee import TeeInput
from gunicorn.util import CHUNK_SIZE

NORMALIZE_SPACE = re.compile(r'(?:\r\n)?[ \t]+')

class RequestError(Exception):
    pass
        
class Request(object):

    RESPONSE_CLASS = Response
    SERVER_VERSION = "gunicorn/%s" % __version__
    
    DEFAULTS = {
        "wsgi.url_scheme": 'http',
        "wsgi.input": StringIO(),
        "wsgi.errors": sys.stderr,
        "wsgi.version": (1, 0),
        "wsgi.multithread": False,
        "wsgi.multiprocess": True,
        "wsgi.run_once": False,
        "SCRIPT_NAME": "",
        "SERVER_SOFTWARE": "gunicorn/%s" % __version__
    }

    def __init__(self, cfg, socket, client_address, server_address):
        self.cfg = cfg
        self.socket = socket
    
        self.client_address = client_address
        self.server_address = server_address
        self.response_status = None
        self.response_headers = []
        self._version = 11
        self.parser = Parser.parse_request()
        self.log = logging.getLogger(__name__)
        self.response = None
        self.response_chunked = False
        self.headers_sent = False

    def read(self):
        environ = {}
        headers = []
        buf = StringIO()
        data = self.socket.recv(CHUNK_SIZE)
        buf.write(data)
        buf2 = self.parser.filter_headers(headers, buf)
        if not buf2:
            while True:
                data = self.socket.recv(CHUNK_SIZE)
                if not data:
                    break
                buf.write(data)
                buf2 = self.parser.filter_headers(headers, buf)
                if buf2: 
                    break
                    
        self.log.debug("%s", self.parser.status)
        self.log.debug("Headers:\n%s" % headers)
        
        if self.parser.headers_dict.get('Expect','').lower() == "100-continue":
            self.socket.send("HTTP/1.1 100 Continue\r\n\r\n")
            
        if not self.parser.content_len and not self.parser.is_chunked:
            wsgi_input = TeeInput(self.cfg, self.socket, self.parser, StringIO())
            content_length = "0"
        else:
            wsgi_input = TeeInput(self.cfg, self.socket, self.parser, buf2)
            content_length = str(wsgi_input.len)
                
        # This value should evaluate true if an equivalent application
        # object may be simultaneously invoked by another process, and
        # should evaluate false otherwise. In debug mode we fall to one
        # worker so we comply to pylons and other paster app.
        wsgi_multiprocess = self.cfg.workers > 1

        # authors should be aware that REMOTE_HOST and REMOTE_ADDR
        # may not qualify the remote addr:
        # http://www.ietf.org/rfc/rfc3875
        client_address = self.client_address or "127.0.0.1"
        forward_adress = self.parser.headers_dict.get('X-Forwarded-For', 
                                                client_address)
                                                
        if self.parser.headers_dict.get("X-Forwarded-Protocol") == "https" or \
            self.parser.headers_dict.get("X-Forwarded-Ssl") == "on":
                url_scheme = "https"
        else:
            url_scheme = "http"
        
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
            "wsgi.url_scheme": url_scheme,
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
            "CONTENT_LENGTH": content_length,
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
        
    def start_response(self, status, headers, exc_info=None):
        if exc_info:
            try:
                if self.response and self.response.headers_sent:
                    raise exc_info[0], exc_info[1], exc_info[2]
            finally:
                exc_info = None
        elif self.response is not None:
            raise AssertionError("Response headers already set!")

        self.response = self.RESPONSE_CLASS(self, status, headers)
        return self.response.write

class KeepAliveRequest(Request):

    RESPONSE_CLASS = KeepAliveResponse

    def read(self):
        try:
            return super(KeepAliveRequest, self).read()
        except socket.error, e:
            if e[0] == errno.ECONNRESET:
                return
            raise
