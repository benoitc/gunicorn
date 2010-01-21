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
from gunicorn.http.parser import HttpParser
from gunicorn.http.tee import TeeInput
from gunicorn.util import CHUNK_SIZE, read_partial, \
normalize_name


NORMALIZE_SPACE = re.compile(r'(?:\r\n)?[ \t]+')




class RequestError(Exception):
    """ raised when something wrong happend"""
        

class HttpRequest(object):
    
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


    def __init__(self, socket, client_address, server_address):
        self.socket = socket
        self.client_address = client_address
        self.server_address = server_address
        self.response_status = None
        self.response_headers = {}
        self._version = 11
        self.parser = HttpParser()
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

        self.log.debug("Got headers:\n%s" % headers)
        
        if self.parser.headers_dict.get('Except', '').lower() == "100-continue":
            self.socket.send("100 Continue\n")
            
        if not self.parser.content_len and not self.parser.is_chunked:
            wsgi_input = StringIO.StringIO()
        else:
            wsgi_input = TeeInput(self.socket, self.parser, buf[i:])
                
        environ = {
            "wsgi.url_scheme": 'http',
            "wsgi.input": wsgi_input,
            "wsgi.errors": sys.stderr,
            "wsgi.version": (1, 0),
            "wsgi.multithread": False,
            "wsgi.multiprocess": True,
            "wsgi.run_once": False,
            "SCRIPT_NAME": "",
            "SERVER_SOFTWARE": self.SERVER_VERSION,
            "REQUEST_METHOD": self.parser.method,
            "PATH_INFO": unquote(self.parser.path),
            "QUERY_STRING": self.parser.query_string,
            "RAW_URI": self.parser.raw_path,
            "CONTENT_TYPE": self.parser.headers_dict.get('Content-Type', ''),
            "CONTENT_LENGTH": str(wsgi_input.len),
            "REMOTE_ADDR": self.client_address[0],
            "REMOTE_PORT": self.client_address[1],
            "SERVER_NAME": self.server_address[0],
            "SERVER_PORT": self.server_address[1],
            "SERVER_PROTOCOL": self.parser.raw_version
        }
        
        for key, value in self.parser.headers:
            key = 'HTTP_' + key.upper().replace('-', '_')
            if key not in ('HTTP_CONTENT_TYPE', 'HTTP_CONTENT_LENGTH'):
                environ[key] = value

        return environ
        
    def start_response(self, status, response_headers):
        self.response_status = status
        for name, value in response_headers:
            name = normalize_name(name)
            if not isinstance(value, basestring):
                value = str(value)
            self.response_headers[name] = value.strip()        
        self.start_response_called = True
