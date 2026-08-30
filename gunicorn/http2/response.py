#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""WSGI response writer for HTTP/2 streams."""

from gunicorn import util
from gunicorn.http.wsgi import Response
from gunicorn.http2.errors import HTTP2StreamError


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

    def _aborted(self, what):
        # The stream is gone (peer reset, connection lost) or stalled past
        # cfg.timeout; the connection has already reset it. Stop the
        # application here rather than letting it write into the void.
        self._stream_ended = True
        raise HTTP2StreamError(self.stream_id, f"response aborted: {what}")

    def send_headers(self):
        if self.headers_sent:
            return
        # The same server headers HTTP/1 adds
        names = {name.lower() for name, _ in self.headers}
        headers = list(self.headers)
        if "server" not in names:
            headers.append(("server", self.version))
        if "date" not in names:
            headers.append(("date", util.http_date()))
        if not self.h2_conn.send_response_headers(
                self.stream_id, self.status_code, headers, end_stream=False):
            self._aborted("stream closed before headers were sent")
        self.headers_sent = True

    def _emit_body(self, data):
        if not data or self._stream_ended:
            return
        if not self.h2_conn.send_data(self.stream_id, data, end_stream=False):
            self._aborted("stream closed or stalled while sending the body")

    def close(self):
        if self._stream_ended:
            return
        if not self.headers_sent:
            self.send_headers()
        self._stream_ended = True
        trailers = getattr(self, "trailers", None)
        if not self.h2_conn.end_stream(self.stream_id, trailers=trailers):
            self._aborted("stream closed before the response was complete")
