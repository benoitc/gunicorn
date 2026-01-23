#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import ssl

from gunicorn.http.message import Request
from gunicorn.http.unreader import SocketUnreader, IterUnreader


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

        # request counter (for keepalive connetions)
        self.req_count = 0

    def __iter__(self):
        return self

    def finish_body(self):
        """Discard any unread body of the current message.

        This should be called before returning a keepalive connection to
        the poller to ensure the socket doesn't appear readable due to
        leftover body bytes.
        """
        if self.mesg:
            try:
                data = self.mesg.body.read(1024)
                while data:
                    data = self.mesg.body.read(1024)
            except ssl.SSLWantReadError:
                # SSL socket has no more application data available
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
