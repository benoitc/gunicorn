#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""WSGI response writer for HTTP/2 streams."""

from gunicorn.http.wsgi import Response


class HTTP2Response(Response):
    """A WSGI Response that frames its output as HTTP/2 instead of HTTP/1.

    Only the wire framing is overridden. Everything the WSGI protocol needs
    (``start_response``, header processing, the no-body rules for HEAD, 1xx,
    204 and 304, the Content-Length accounting in ``write()``) is inherited,
    so HTTP/2 responses obey the same rules as HTTP/1 ones rather than a
    parallel set that has to be kept in step by hand.
    """

    def __init__(self, req, sock, cfg, h2_conn, stream_id):
        # sock is unused: every write goes through the HTTP/2 connection.
        # The signature matches Response so wsgi.create() can build either.
        super().__init__(req, sock, cfg)
        self.h2_conn = h2_conn
        self.stream_id = stream_id
        self._stream_ended = False

    def is_chunked(self):
        # HTTP/2 has its own framing; chunked transfer coding is forbidden
        # (RFC 9113 section 8.1).
        return False

    def can_sendfile(self):
        # sendfile() writes raw bytes to a socket, which would bypass HTTP/2
        # framing entirely. Base Response guards this with cfg.is_ssl, which
        # happens to cover HTTP/2 over TLS but not over cleartext.
        return False

    def send_headers(self):
        if self.headers_sent:
            return
        self.h2_conn.send_response_headers(
            self.stream_id, self.status_code, self.headers, end_stream=False
        )
        self.headers_sent = True

    def _emit_body(self, data):
        if not data:
            return
        self.h2_conn.send_data(self.stream_id, data, end_stream=False)

    def close(self):
        if not self.headers_sent:
            self.send_headers()
        if self._stream_ended:
            return
        self._stream_ended = True
        trailers = getattr(self, "trailers", None)
        self.h2_conn.end_stream(self.stream_id, trailers=trailers)
