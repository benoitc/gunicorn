# -*- coding: utf-8 -*-
#
# Copyright 2008,2009 Benoit Chesneau <benoitc@e-engura.org>
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at#
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import re
import StringIO
import sys
from urllib import unquote

from gunicorn import __version__

NORMALIZE_SPACE = re.compile(r'(?:\r\n)?[ \t]+')

def _normalize_name(name):
    return ["-".join([w.capitalize() for w in name.split("-")])]

class RequestError(Exception):
    
    def __init__(self, status_code, reason):
        self.status_code = status_code
        self.reason = reason
        Exception.__init__(self, (status_code, reason))

class HTTPRequest(object):
    
    SERVER_VERSION = "gunicorn/%s" % __version__
    CHUNK_SIZE = 4096
    
    def __init__(self, socket, client_address, server_address):
        self.socket = socket
        self.client_address = client_address
        self.server_address = server_address
        self.version = None
        self.method = None
        self.path = None
        self.headers = {}
        self.response_status = None
        self.response_headers = {}
        self._version = 11
        self.fp = socket.makefile("rw", self.CHUNK_SIZE)
        

    def read(self):
        # get status line
        self.first_line(self.fp.readline())
        
        # read headers
        self.read_headers()
        
        if "?" in self.path:
            path_info, query = self.path.split('?', 1)
        else:
            path_info = self.path
            query = ""
            
        length = self.body_length()
        if not length:
            wsgi_input = StringIO.StringIO()
        elif length == "chunked":
            length, wsgi_input = self.decode_chunked()
        else:
             wsgi_input = FileInput(self)
                 
                
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
            "REQUEST_METHOD": self.method,
            "PATH_INFO": unquote(path_info),
            "QUERY_STRING": query,
            "RAW_URI": self.path,
            "CONTENT_TYPE": self.headers.get('content-type', ''),
            "CONTENT_LENGTH": length,
            "REMOTE_ADDR": self.client_address[0],
            "REMOTE_PORT": self.client_address[1],
            "SERVER_NAME": self.server_address[0],
            "SERVER_PORT": self.server_address[1],
            "SERVER_PROTOCOL": self.version
        }
        
        for key, value in self.headers.items():
            key = 'HTTP_' + key.replace('-', '_')
            if key not in ('HTTP_CONTENT_TYPE', 'HTTP_CONTENT_LENGTH'):
                environ[key] = value
        return environ
        
    def read_headers(self):
        hname = ""
        while True:
            line = self.fp.readline()

            if line == "\r\n": 
                # end of headers
                break
            
            if line == "\t":
                 # It's a continuation line.
                self.headers[hname] += line.strip()
            else:
                try:
                    hname =self.parse_header(line)
                except ValueError: 
                    # bad headers
                    pass

    def body_length(self):
        transfert_encoding = self.headers.get('TRANSFERT-ENCODING')
        content_length = self.headers.get('CONTENT-LENGTH')
        if transfert_encoding is None:
            if content_length is None:
                return None
            return content_length
        elif transfert_encoding == "chunked":
            return "chunked"
        else:
            return None
         
    def should_close(self):
        if self.headers.get("CONNECTION") == "close":
            return True
        if self.headers.get("CONNECTION") == "Keep-Alive":
            return False
        if self.version < "HTTP/1.1":
            return True        
            
    def decode_chunked(self):
        """Decode the 'chunked' transfer coding."""
        length = 0
        data = StringIO.StringIO()
        while True:
            line = self.fp.readline().strip().split(";", 1)
            chunk_size = int(line.pop(0), 16)
            if chunk_size <= 0:
                break
            length += chunk_size
            data.write(self.fp.read(chunk_size))
            crlf = self.fp.read(2)
            if crlf != "\r\n":
                raise RequestError((400, "Bad chunked transfer coding "
                                         "(expected '\\r\\n', got %r)" % crlf))
                return

        # Grab any trailer headers
        self.read_headers()

        data.seek(0)
        return data, str(length) or ""
        
    def start_response(self, status, response_headers):
        resp_head = []
        self.response_status = status
        self.response_headers = {}
        resp_head.append("%s %s" % (self.version, status))
        for name, value in response_headers:
            resp_head.append("%s: %s" % (name, value))
            self.response_headers[name.lower()] = value
        self.fp.write("%s\r\n\r\n" % "\r\n".join(resp_head))
        
    def write(self, data):
        self.fp.write(data)
        
    def close(self):
        self.fp.close()
        if self.should_close():
            self.socket.close()

    def first_line(self, line):
        method, path, version = line.strip().split(" ")
        self.version = version.strip()
        self.method = method.upper()
        self.path = path
        
    def parse_header(self, line):
        name, value = line.split(": ", 1)
        name = name.strip().upper()
        self.headers[name] = value.strip()
        return name
        
        
        
class FileInput(object):
    
    def __init__(self, req):
        self.length = req.body_length()
        self.fp = req.fp
        self.eof = False
        
    def close(self):
        self.eof = False

    def read(self, amt=None):
        if self.fp is None or self.eof:
            return ''

        if amt is None:
            # unbounded read
            s = self._safe_read(self.length)
            self.close()     # we read everything
            return s

        if amt > self.length:
            amt = self.length

        s = self.fp.read(amt)
        self.length -= len(s)
        if not self.length:
            self.close()
        return s

    def readline(self, size=None):
        if self.fp is None or self.eof:
            return ''
        
        if size is not None:
            data = self.fp.readline(size)
        else:
            # User didn't specify a size ...
            # We read the line in chunks to make sure it's not a 100MB line !
            # cherrypy trick
            res = []
            while True:
                data = self.fp.readline(256)
                res.append(data)
                if len(data) < 256 or data[-1:] == "\n":
                    data = ''.join(res)
                    break
        self.length -= len(data)
        if not self.length:
            self.close()
        return data
    
    def readlines(self, sizehint=0):
        # Shamelessly stolen from StringIO
        total = 0
        lines = []
        line = self.readline()
        while line:
            lines.append(line)
            total += len(line)
            if 0 < sizehint <= total:
                break
            line = self.readline()
        return lines


    def _safe_read(self, amt):
        """Read the number of bytes requested, compensating for partial reads.
        """
        s = []
        while amt > 0:
            chunk = self.fp.read(amt)
            if not chunk:
                raise RequestError(500, "Incomplete read %s" % s)
            s.append(chunk)
            amt -= len(chunk)
        return ''.join(s)
        
        
    def __iter__(self):
        return self
        
    def next(self):
        if self.eof:
            raise StopIteration()
        return self.readline()
        
        
        