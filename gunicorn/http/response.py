# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from gunicorn.util import  close, http_date, write, write_chunk

class Response(object):
    
    def __init__(self, sock, response, req):
        self.req = req
        self._sock = sock
        self.data = response
        self.headers = req.response_headers or []
        self.status = req.response_status
        self.SERVER_VERSION = req.SERVER_VERSION
        self.chunked = req.response_chunked

    def send(self):
        # send headers
        resp_head = [
            "HTTP/1.1 %s\r\n" % self.status,
            "Server: %s\r\n" % self.SERVER_VERSION,
            "Date: %s\r\n" % http_date(),
            "Connection: close\r\n"
        ]
        resp_head.extend(["%s: %s\r\n" % (n, v) for n, v in self.headers])
        write(self._sock, "%s\r\n" % "".join(resp_head))

        for chunk in list(self.data):
            if chunk == "": break
            write(self._sock, chunk, self.chunked)
            
        if self.chunked:
                # send last chunk
                write_chunk(self._sock, "")

        close(self._sock)

        if hasattr(self.data, "close"):
            self.data.close()
