#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import socket
import ssl
import time

from gunicorn.http.message import Request
from gunicorn.http.unreader import SocketUnreader, IterUnreader


# Cap on bytes drained from an unconsumed request body before a keepalive
# reset.  Defends against a slow-but-steady client that stays under a per-read
# deadline yet streams indefinitely.
_DRAIN_MAX_BYTES = 64 * 1024


class Parser:

    mesg_class = None

    def __init__(self, cfg, source, source_addr):
        self.cfg = cfg
        if hasattr(source, "recv"):
            self.unreader = SocketUnreader(source)
        else:
            self.unreader = IterUnreader(source)
        self.mesg = None
        self.source_addr = source_addr

        # request counter (for keepalive connections)
        self.req_count = 0

    def __iter__(self):
        return self

    def finish_body(self, deadline=None, max_bytes=None):
        """Discard any unread body of the current message.

        Called before returning a keepalive connection to the poller so the
        socket does not appear readable due to leftover body bytes.

        ``deadline`` is an absolute ``time.monotonic()`` value; when set the
        socket read timeout is bounded by the remaining time before each read.
        ``max_bytes`` caps the total drained bytes; when a deadline is given
        and ``max_bytes`` is left at the default, ``_DRAIN_MAX_BYTES`` applies
        to defend against a slow client that keeps trickling under it.  When
        called without a deadline (the default invocation from ``__next__``),
        no byte cap is applied so the prior unbounded drain semantics are
        preserved for callers that don't know how to react to a partial drain.

        Returns ``True`` when the body was fully drained, ``False`` when the
        drain was abandoned (deadline, byte cap, or socket timeout).  Callers
        that observe ``False`` MUST close the connection rather than serve
        another request on it.
        """
        if not self.mesg:
            return True

        if max_bytes is None and deadline is not None:
            max_bytes = _DRAIN_MAX_BYTES

        sock = getattr(self.unreader, "sock", None)
        # gettimeout/settimeout only matter when bounding a real socket; a
        # mock or non-socket source skips the timeout plumbing.
        if sock is not None and hasattr(sock, "gettimeout") and hasattr(sock, "settimeout"):
            timeoutable_sock = sock
            prior_timeout = sock.gettimeout()
        else:
            timeoutable_sock = None
            prior_timeout = None

        drained = 0
        try:
            while True:
                if deadline is not None and timeoutable_sock is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    timeoutable_sock.settimeout(remaining)
                try:
                    data = self.mesg.body.read(1024)
                except (socket.timeout, TimeoutError):
                    return False
                except ssl.SSLWantReadError:
                    # SSL socket has no more application data available
                    return True
                if not data:
                    return True
                drained += len(data)
                if max_bytes is not None and drained >= max_bytes:
                    return False
        finally:
            if timeoutable_sock is not None:
                try:
                    timeoutable_sock.settimeout(prior_timeout)
                except OSError:
                    pass

    def __next__(self):
        # Stop if HTTP dictates a stop.
        if self.mesg and self.mesg.should_close():
            raise StopIteration()

        # Discard any unread body of the previous message
        self.finish_body()

        # Parse the next request
        self.req_count += 1
        self.mesg = self.mesg_class(self.cfg, self.unreader, self.source_addr, self.req_count)
        if not self.mesg:
            raise StopIteration()
        return self.mesg

    next = __next__


class RequestParser(Parser):

    mesg_class = Request
