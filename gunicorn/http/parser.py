# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from gunicorn.http.message import Request
from gunicorn.http.unreader import SocketUnreader, IterUnreader

class Parser(object):
    def __init__(self, mesg_class, cfg, source):
        self.mesg_class = mesg_class
        self.cfg = cfg
        if hasattr(source, "recv"):
            self.unreader = SocketUnreader(source)
        else:
            self.unreader = IterUnreader(source)
        self.mesg = None

    def __iter__(self):
        return self

    def next(self):
        # Stop if HTTP dictates a stop.
        if self.mesg and self.mesg.should_close():
            raise StopIteration()

        # Discard any unread body of the previous message
        if self.mesg:
            data = self.mesg.body.read(8192)
            while data:
                data = self.mesg.body.read(8192)

        # Parse the next request
        self.mesg = self.mesg_class(self.cfg, self.unreader)
        if not self.mesg:
            raise StopIteration()
        return self.mesg

class RequestParser(Parser):
    def __init__(self, *args, **kwargs):
        super(RequestParser, self).__init__(Request, *args, **kwargs)

