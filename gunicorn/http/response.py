# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from gunicorn.util import  close, http_date, write, write_chunk

class Response(object):
    
    def __init__(self, sock, response, req):
        self.req = req
        self.sock = sock
        self.data = response
        self.headers = req.response_headers or []
        self.status = req.response_status
        self.SERVER_VERSION = req.SERVER_VERSION
        self.chunked = req.response_chunked

    def send(self):
        # send headers
        resp_head = []    
        resp_head.append("HTTP/1.0 %s\r\n" % (self.status))
    
        resp_head.append("Server: %s\r\n" % self.SERVER_VERSION)
        resp_head.append("Date: %s\r\n" % http_date())
        # broken clients
        resp_head.append("Status: %s\r\n" % str(self.status))
        # always close the connection
        resp_head.append("Connection: close\r\n")        
        for name, value in self.headers:
            resp_head.append("%s: %s\r\n" % (name, value))
        
        write(self.sock, "%s\r\n" % "".join(resp_head))

        last_chunk = None
        for chunk in list(self.data):
            write(self.sock, chunk, self.chunked)
            last_chunk = chunk
            
        if self.chunked:
            if last_chunk or last_chunk is None:
                # send last chunk
                write_chunk("")

        close(self.sock)

        if hasattr(self.data, "close"):
            self.data.close()
