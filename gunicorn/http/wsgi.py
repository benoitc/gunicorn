# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import logging
import os
import re
import sys
from urllib import unquote

from gunicorn import SERVER_SOFTWARE
import gunicorn.util as util

NORMALIZE_SPACE = re.compile(r'(?:\r\n)?[ \t]+')

log = logging.getLogger(__name__)

def create(req, sock, client, server, cfg):
    resp = Response(req, sock)

    environ = {
        "wsgi.input": req.body,
        "wsgi.errors": sys.stderr,
        "wsgi.version": (1, 0),
        "wsgi.multithread": False,
        "wsgi.multiprocess": (cfg.workers > 1),
        "wsgi.run_once": False,
        "gunicorn.socket": sock,
        "SERVER_SOFTWARE": SERVER_SOFTWARE,
        "REQUEST_METHOD": req.method,
        "QUERY_STRING": req.query,
        "RAW_URI": req.uri,
        "SERVER_PROTOCOL": "HTTP/%s" % ".".join(map(str, req.version)),
        "CONTENT_TYPE": "",
        "CONTENT_LENGTH": ""
    }
    
    # authors should be aware that REMOTE_HOST and REMOTE_ADDR
    # may not qualify the remote addr:
    # http://www.ietf.org/rfc/rfc3875
    client = client or "127.0.0.1"
    forward = client
    url_scheme = "http"
    script_name = os.environ.get("SCRIPT_NAME", "")

    for hdr_name, hdr_value in req.headers:
        if hdr_name == "EXPECT":
            # handle expect
            if hdr_value.lower() == "100-continue":
                sock.send("HTTP/1.1 100 Continue\r\n\r\n")
        elif hdr_name == "X-FORWARDED-FOR":
            forward = hdr_value
        elif hdr_name == "X-FORWARDED-PROTOCOL" and hdr_value.lower() == "ssl":
            url_scheme = "https"
        elif hdr_name == "X-FORWARDED-SSL" and hdr_value.lower() == "on":
            url_scheme = "https"
        elif hdr_name == "HOST":
            server = hdr_value
        elif hdr_name == "SCRIPT_NAME":
            script_name = hdr_value
        elif hdr_name == "CONTENT-TYPE":
            environ['CONTENT_TYPE'] = hdr_value
            continue
        elif hdr_name == "CONTENT-LENGTH":
            environ['CONTENT_LENGTH'] = hdr_value
            continue
        
        key = 'HTTP_' + hdr_name.replace('-', '_')
        environ[key] = hdr_value

    environ['wsgi.url_scheme'] = url_scheme
        

    if isinstance(forward, basestring):
        # we only took the last one
        # http://en.wikipedia.org/wiki/X-Forwarded-For
        if forward.find(",") >= 0:
            forward = forward.rsplit(",", 1)[1].strip()
        remote = forward.split(":")
        if len(remote) < 2:
            remote.append('80')
    else:
        remote = forward 

    environ['REMOTE_ADDR'] = remote[0]
    environ['REMOTE_PORT'] = str(remote[1])

    if isinstance(server, basestring):
        server =  server.split(":")
        if len(server) == 1:
            if url_scheme == "http":
                server.append("80")
            elif url_scheme == "https":
                server.append("443")
            else:
                server.append('')
    environ['SERVER_NAME'] = server[0]
    environ['SERVER_PORT'] = server[1]

    path_info = req.path
    if script_name:
        path_info = path_info.split(script_name, 1)[1]
    environ['PATH_INFO'] = unquote(path_info)
    environ['SCRIPT_NAME'] = script_name

    return resp, environ

class Response(object):

    def __init__(self, req, sock):
        self.req = req
        self.sock = sock
        self.version = SERVER_SOFTWARE
        self.status = None
        self.chunked = False
        self.should_close = req.should_close()
        self.headers = []
        self.headers_sent = False

    def force_close(self):
        self.should_close = True

    def start_response(self, status, headers, exc_info=None):
        if exc_info:
            try:
                if self.status and self.headers_sent:
                    raise exc_info[0], exc_info[1], exc_info[2]
            finally:
                exc_info = None
        elif self.status is not None:
            raise AssertionError("Response headers already set!")

        self.status = status
        self.process_headers(headers)
        return self.write

    def process_headers(self, headers):
        for name, value in headers:
            assert isinstance(name, basestring), "%r is not a string" % name
            if util.is_hoppish(name):
                lname = name.lower().strip()
                if lname == "transfer-encoding":
                    if value.lower().strip() == "chunked":
                        self.chunked = True
                elif lname == "connection":
                    # handle websocket
                    if value.lower().strip() != "upgrade":
                        continue
                else:
                    # ignore hopbyhop headers
                    continue
            self.headers.append((name.strip(), str(value).strip()))

    def default_headers(self):
        connection = "keep-alive"
        if self.should_close:
            connection = "close"

        return [
            "HTTP/1.1 %s\r\n" % self.status,
            "Server: %s\r\n" % self.version,
            "Date: %s\r\n" % util.http_date(),
            "Connection: %s\r\n" % connection
        ]

    def send_headers(self):
        if self.headers_sent:
            return
        tosend = self.default_headers()
        tosend.extend(["%s: %s\r\n" % (n, v) for n, v in self.headers])
        util.write(self.sock, "%s\r\n" % "".join(tosend))
        self.headers_sent = True

    def write(self, arg):
        self.send_headers()
        assert isinstance(arg, basestring), "%r is not a string." % arg
        util.write(self.sock, arg, self.chunked)

    def close(self):
        if not self.headers_sent:
            self.send_headers()
        if self.chunked:
            util.write_chunk(self.sock, "")
