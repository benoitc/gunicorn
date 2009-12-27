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

from gunicorn.util import http_date

class HTTPResponse(object):
    
    def __init__(self, req, data):
        self.req = req
        self.data = data
        self.headers = self.req.response_headers or {}
        self.io = req.io

    def write(self, data):
        self.io.send(data)
        
    def send(self):
        # send headers
        resp_head = []    
        resp_head.append("%s %ss\r\n" % (self.req.version, self.req.response_status))
        
        resp_head.append("Server: %s\r\n" % self.req.SERVER_VERSION)
        resp_head.append("Date: %s\r\n" % http_date())
        # broken clients
        resp_head.append("Status: %s\r\n" % str(self.req.response_status))        
        for name, value in self.req.response_headers.items():
            resp_head.append("%s: %s\r\n" % (name, value))
        self.io.send("%s\r\n" % "".join(resp_head))

        for chunk in self.data:
            self.write(chunk)
        self.req.close()
        
        if hasattr(self.data, "close"):
            self.data.close()
    