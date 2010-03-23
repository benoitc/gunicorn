# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from gunicorn.util import  close, http_date, write, write_chunk, is_hoppish

class Response(object):
    
    def __init__(self, req, status, headers):
        self.req = req
        self.version = req.SERVER_VERSION
        self.status = status
        self.chunked = False
        self.headers = []
        self.headers_sent = False

        for name, value in headers:
            assert isinstance(name, basestring), "%r is not a string" % name
            assert isinstance(value, basestring), "%r is not a string" % value
            assert not is_hoppish(name), "%s is a hop-by-hop header." % name
            if name.lower().strip() == "transfer-encoding":
                if value.lower().strip() == "chunked":
                    self.chunked = True
            self.headers.append((name.strip(), value.strip()))

    def send_headers(self):
        if self.headers_sent:
            return
        tosend = [
            "HTTP/1.1 %s\r\n" % self.status,
            "Server: %s\r\n" % self.version,
            "Date: %s\r\n" % http_date(),
            "Connection: close\r\n"
        ]
        tosend.extend(["%s: %s\r\n" % (n, v) for n, v in self.headers])
        write(self.req.socket, "%s\r\n" % "".join(tosend))
        self.headers_sent = True

    def write(self, arg):
        self.send_headers()
        assert isinstance(arg, basestring), "%r is not a string." % arg
        write(self.req.socket, arg, self.chunked)

    def close(self):
        if self.chunked:
            write_chunk(self.socket, "")
        close(self.req.socket)
