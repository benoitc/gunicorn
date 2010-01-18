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

import errno
import socket
import select
import time

import os
from gunicorn.util import http_date, write, read_partial, close

class HTTPResponse(object):
    
    def __init__(self, sock, response, req):
        self.req = req
        self.sock = sock.dup()
        self.data = response
        self.headers = req.response_headers or {}
        self.status = req.response_status
        self.SERVER_VERSION = req.SERVER_VERSION

    def send(self):
        # send headers
        resp_head = []    
        resp_head.append("HTTP/1.0 %s\r\n" % (self.status))
    
        resp_head.append("Server: %s\r\n" % self.SERVER_VERSION)
        resp_head.append("Date: %s\r\n" % http_date())
        # broken clients
        resp_head.append("Status: %s\r\n" % str(self.status))
        # always close the conenction
        #resp_head.append("Connection: close\r\n")        
        for name, value in self.headers.items():
            resp_head.append("%s: %s\r\n" % (name, value))
        
        write(self.sock, "%s\r\n" % "".join(resp_head))

        for chunk in self.data:
            write(self.sock, chunk)
          

        close(self.sock)

        if hasattr(self.data, "close"):
            self.data.close()