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

from simplehttp import RequestParser

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
        self.parser = RequestParser(self.socket)
        self.log = logging.getLogger(__name__)
        self.response = None
        self.response_chunked = False
        self.headers_sent = False
        self.req = None

    def read(self):
        environ = {}
        headers = []
        
        ended = False
        req = None
        
        self.req = req = self.parser.next()
        
        ##self.log.debug("%s", self.parser.status)
        self.log.debug("Headers:\n%s" % req.headers)
        
        # authors should be aware that REMOTE_HOST and REMOTE_ADDR
        # may not qualify the remote addr:
        # http://www.ietf.org/rfc/rfc3875
        client_address = self.client_address or "127.0.0.1"
        forward_address = client_address
        server_address = self.server_address
        script_name = os.environ.get("SCRIPT_NAME", "")
        content_type = ""
        for hdr_name, hdr_value in req.headers:
            name = hdr_name.lower()
            if name == "expect":
                # handle expect
                if hdr_value.lower() == "100-continue":
                    self.socket.send("HTTP/1.1 100 Continue\r\n\r\n")
            elif name == "x-forwarded-for":
                forward_address = hdr_value
            elif name == "host":
                host = hdr_value
            elif name == "script_name":
                script_name = hdr_value
            elif name == "content-type":
                content_type = hdr_value
                
        
        wsgi_input = req.body
        if hasattr(req.body, "length"):
            content_length = str(req.body.length)
        else:
            content_length = None
                
        # This value should evaluate true if an equivalent application
        # object may be simultaneously invoked by another process, and
        # should evaluate false otherwise. In debug mode we fall to one
        # worker so we comply to pylons and other paster app.
        wsgi_multiprocess = self.cfg.workers > 1

        if isinstance(forward_address, basestring):
            # we only took the last one
            # http://en.wikipedia.org/wiki/X-Forwarded-For
            if "," in forward_address:
                forward_adress = forward_address.split(",")[-1].strip()
            remote_addr = forward_address.split(":")
            if len(remote_addr) == 1:
                remote_addr.append('')
        else:
            remote_addr = forward_address

        if isinstance(server_address, basestring):
            server_address =  server_address.split(":")
            if len(server_address) == 1:
                server_address.append('')

        path_info = req.path
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
            "REQUEST_METHOD": req.method,
            "PATH_INFO": unquote(path_info),
            "QUERY_STRING": req.query,
            "RAW_URI": req.path,
            "CONTENT_TYPE": content_type,
            "CONTENT_LENGTH": content_length,
            "REMOTE_ADDR": remote_addr[0],
            "REMOTE_PORT": str(remote_addr[1]),
            "SERVER_NAME": server_address[0],
            "SERVER_PORT": str(server_address[1]),
            "SERVER_PROTOCOL": req.version
        }
        
        for key, value in req.headers:
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
