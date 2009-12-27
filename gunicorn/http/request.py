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

import re
import StringIO
import sys
from urllib import unquote


from gunicorn import __version__
from gunicorn.http.iostream import IOStream



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
        self.io = IOStream(socket)
        self.start_response_called = False
        self._should_close = False
        
    def read(self):
        # read headers
        self.read_headers(first_line=True)
        
        if self.headers.get('ACCEPT', '').lower() == "100-continue":
            self.io.send("100 Continue\n")
            
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
            "CONTENT_TYPE": self.headers.get('CONTENT-TYPE', ''),
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
        
    def read_headers(self, first_line=False):
        headers_str = self.io.read_until("\r\n\r\n")
        lines = headers_str.split("\r\n")
        self.first_line(lines.pop(0))
        hname = ""
        for line in lines:
            if line == "\t":
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
        if self._should_close:
            return True
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
        
    def write(self, data):
        self.io.write(send)
        
    def close(self):
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
    
    stream_size = 4096
    
    def __init__(self, req):
        self.req = req
        self.length = int(req.body_length() or 0)
        self.io = req.io
        self._rbuf = ""
        self.size = 0
        
    def close(self):
        self.eof = False

    def read(self, amt=None):
        if self.length and self.size >= self.length:
            return ''

        if self._rbuf and amt is not None:
            L = len(self._rbuf)
            print L
            if amt > L:
                amt -= L
            else:
                s = self._rbuf[:amt]
                self._rbuf = self._rbuf[amt:]
                self.size += len(s)
                return s
                
        if amt is None:
            amt = min(self. stream_size, self.length or 0)
            
        data = self.req.io.recv(amt)
        s = self._rbuf + data
        self._rbuf = ''
        self.size += len(s)
        return s

    def readline(self, amt=-1):
        i = self._rbuf.find('\n')
        while i < 0 and not (0 < amt <= len(self._rbuf)):
            new = self.io.recv(self.stream_size)
            if not new: break
            i = new.find('\n')
            if i >= 0: 
                i = i + len(self._rbuf)
            self._rbuf = self._rbuf + new
        if i < 0: 
            i = len(self._rbuf)
        else: 
            i = i+1
        if 0 <= amt < len(self._rbuf): 
            i = amt
        data, self._rbuf = self._rbuf[:i], self._rbuf[i:]
        return data

    def readlines(self, sizehint=0):
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

    def next(self):
        r = self.readline()
        if not r:
            raise StopIteration
        return r

    def __iter__(self):
        return self
        
        
        