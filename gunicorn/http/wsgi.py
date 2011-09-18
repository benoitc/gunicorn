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

try:
    # Python 3.3 has os.sendfile().
    from os import sendfile
except ImportError:
    try:
        from _sendfile import sendfile
    except ImportError:
        sendfile = None

NORMALIZE_SPACE = re.compile(r'(?:\r\n)?[ \t]+')

log = logging.getLogger(__name__)

class FileWrapper:

    def __init__(self, filelike, blksize=8192):
        self.filelike = filelike
        self.blksize = blksize
        if hasattr(filelike, 'close'):
            self.close = filelike.close

    def __getitem__(self, key):
        data = self.filelike.read(self.blksize)
        if data:
            return data
        raise IndexError

def create(req, sock, client, server, cfg):
    resp = Response(req, sock)

    environ = {
        "wsgi.input": req.body,
        "wsgi.errors": sys.stderr,
        "wsgi.version": (1, 0),
        "wsgi.multithread": False,
        "wsgi.multiprocess": (cfg.workers > 1),
        "wsgi.run_once": False,
        "wsgi.file_wrapper": FileWrapper,
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

    secure_headers = getattr(cfg, "secure_scheme_headers")

    for hdr_name, hdr_value in req.headers:
        if hdr_name == "EXPECT":
            # handle expect
            if hdr_value.lower() == "100-continue":
                sock.send("HTTP/1.1 100 Continue\r\n\r\n")
        elif hdr_name == "X-FORWARDED-FOR":
            forward = hdr_value
        elif (hdr_name.upper() in secure_headers and
              hdr_value == secure_headers[hdr_name.upper()]):
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

        # find host and port on ipv6 address
        if '[' in forward and ']' in forward:
            host =  forward.split(']')[0][1:].lower()
        elif ":" in forward and forward.count(":") == 1:
            host = forward.split(":")[0].lower()
        else:
            host = forward

        forward = forward.split(']')[-1]
        if ":" in forward and forward.count(":") == 1:
            port = forward.split(':', 1)[1]
        else:
            port = 80

        remote = (host, port)
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
        self.must_close = False
        self.headers = []
        self.headers_sent = False
        self.response_length = None
        self.sent = 0

    def force_close(self):
        self.must_close = True

    def should_close(self):
        if self.must_close or self.req.should_close():
            return True
        if self.response_length is not None or self.chunked:
            return False
        return True

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
        self.chunked = self.is_chunked()
        return self.write

    def process_headers(self, headers):
        for name, value in headers:
            assert isinstance(name, basestring), "%r is not a string" % name
            lname = name.lower().strip()
            if lname == "content-length":
                self.response_length = int(value)
            elif util.is_hoppish(name):
                if lname == "connection":
                    # handle websocket
                    if value.lower().strip() != "upgrade":
                        continue
                else:
                    # ignore hopbyhop headers
                    continue
            self.headers.append((name.strip(), str(value).strip()))


    def is_chunked(self):
        # Only use chunked responses when the client is
        # speaking HTTP/1.1 or newer and there was
        # no Content-Length header set.
        if self.response_length is not None:
            return False
        elif self.req.version <= (1,0):
            return False
        elif self.status.startswith("304") or self.status.startswith("204"):
            # Do not use chunked responses when the response is guaranteed to
            # not have a response body.
            return False
        return True

    def default_headers(self):
        connection = "keep-alive"
        if self.should_close():
            connection = "close"
        headers = [
            "HTTP/%s.%s %s\r\n" % (self.req.version[0],
                self.req.version[1], self.status),
            "Server: %s\r\n" % self.version,
            "Date: %s\r\n" % util.http_date(),
            "Connection: %s\r\n" % connection
        ]
        if self.chunked:
            headers.append("Transfer-Encoding: chunked\r\n")
        return headers

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

        arglen = len(arg)
        tosend = arglen
        if self.response_length is not None:
            if self.sent >= self.response_length:
                # Never write more than self.response_length bytes
                return

            tosend = min(self.response_length - self.sent, tosend)
            if tosend < arglen:
                arg = arg[:tosend]

        # Sending an empty chunk signals the end of the
        # response and prematurely closes the response
        if self.chunked and tosend == 0:
            return

        self.sent += tosend
        util.write(self.sock, arg, self.chunked)

    def sendfile_all(self, fileno, sockno, offset, nbytes):
        # Send file in at most 1GB blocks as some operating
        # systems can have problems with sending files in blocks
        # over 2GB.

        BLKSIZE = 0x3FFFFFFF

        if nbytes > BLKSIZE:
            for m in range(0, nbytes, BLKSIZE):
                self.sendfile_all(fileno, sockno, offset, min(nbytes, BLKSIZE))
                offset += BLKSIZE
                nbytes -= BLKSIZE
        else:
            sent = 0
            sent += sendfile(sockno, fileno, offset+sent, nbytes-sent)
            while sent != nbytes:
                sent += sendfile(sockno, fileno, offset+sent, nbytes-sent)

    def write_file(self, respiter):
        if sendfile is not None and \
                hasattr(respiter.filelike, 'fileno') and \
                hasattr(respiter.filelike, 'tell'):

            fileno = respiter.filelike.fileno()
            fd_offset = os.lseek(fileno, 0, os.SEEK_CUR)
            fo_offset = respiter.filelike.tell()
            nbytes = max(os.fstat(fileno).st_size - fo_offset, 0)

            if self.response_length:
                nbytes = min(nbytes, self.response_length)

            if nbytes == 0:
                return

            self.send_headers()

            if self.is_chunked():
                self.sock.sendall("%X\r\n" % nbytes)

            self.sendfile_all(fileno, self.sock.fileno(), fo_offset, nbytes)

            if self.is_chunked():
                self.sock.sendall("\r\n")

            os.lseek(fileno, fd_offset, os.SEEK_SET)
        else:
            for item in respiter:
                self.write(item)

    def close(self):
        if not self.headers_sent:
            self.send_headers()
        if self.chunked:
            util.write_chunk(self.sock, "")
