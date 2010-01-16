# -*- coding: utf-8 -
#
# 2009 (c) Benoit Chesneau <benoitc@e-engura.com> 
# 2009 (c) Paul J. Davis <paul.joseph.davis@gmail.com>
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following
# conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.

from ctypes import create_string_buffer
import re
import StringIO
import sys
from urllib import unquote


from gunicorn import __version__
from gunicorn.http.http_parser import HttpParser
from gunicorn.http.tee import TeeInput
from gunicorn.util import CHUNK_SIZE


NORMALIZE_SPACE = re.compile(r'(?:\r\n)?[ \t]+')

def _normalize_name(name):
    return  "-".join([w.lower().capitalize() for w in name.split("-")])

class RequestError(Exception):
    
    def __init__(self, status_code, reason):
        self.status_code = status_code
        self.reason = reason
        Exception.__init__(self, (status_code, reason))
        

class HTTPRequest(object):
    
    SERVER_VERSION = "gunicorn/%s" % __version__
    
    def __init__(self, socket, client_address, server_address):
        self.socket = socket.dup()
        self.client_address = client_address
        self.server_address = server_address
        self.response_status = None
        self.response_headers = {}
        self._version = 11
        self.parser = HttpParser()
        self.start_response_called = False
        
    def read(self):
        headers = {}
        remain = CHUNK_SIZE
        buf = create_string_buffer(remain)
        remain -= self.socket.recv_into(buf, remain)
        
        while not self.parser.headers(headers, buf):
            data = create_string_buffer(remain)
            remain -= self.socket.recv_into(data, remain)
            buf =  create_string_buffer(data.value + buf.value)

        print headers
        if headers.get('Except', '').lower() == "100-continue":
            self.socket.send("100 Continue\n")
            
        if "?" in self.parser.path:
            path_info, query = self.parser.path.split('?', 1)
        else:
            path_info = self.parser.path
            query = ""
            
        if not self.parser.content_length and not self.parser.is_chunked:
            wsgi_input = StringIO.StringIO()
        else:
            wsgi_input = TeeInput(self.socket, parser, buf, remain)
                            
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
            "PATH_INFO": unquote(path_info),
            "QUERY_STRING": query,
            "RAW_URI": self.parser.path,
            "CONTENT_TYPE": headers.get('Content-Type', ''),
            "CONTENT_LENGTH": str(wsgi_input.len),
            "REMOTE_ADDR": self.client_address[0],
            "REMOTE_PORT": self.client_address[1],
            "SERVER_NAME": self.server_address[0],
            "SERVER_PORT": self.server_address[1],
            "SERVER_PROTOCOL": self.parser.version
        }
        
        for key, value in headers.items():
            key = 'HTTP_' + key.upper().replace('-', '_')
            if key not in ('HTTP_CONTENT_TYPE', 'HTTP_CONTENT_LENGTH'):
                environ[key] = value
        return environ
        
             
    def decode_chunked(self):
        """Decode the 'chunked' transfer coding."""
        length = 0
        data = StringIO.StringIO()
        while True:
            line = self.io.readuntil("\n").strip().split(";", 1)
            chunk_size = int(line.pop(0), 16)
            if chunk_size <= 0:
                break
            length += chunk_size
            data.write(self.io.recv(chunk_size))
            crlf = self.io.read(2)
            if crlf != "\r\n":
                raise RequestError((400, "Bad chunked transfer coding "
                                         "(expected '\\r\\n', got %r)" % crlf))
                return

        # Grab any trailer headers
        self.read_headers()
        data.seek(0)
        return data, str(length) or ""
        
    def start_response(self, status, response_headers):
        self.response_status = status
        for name, value in response_headers:
            name = _normalize_name(name)
            if not isinstance(value, basestring):
                value = str(value)
            self.response_headers[name] = value.strip()        
        self.start_response_called = True