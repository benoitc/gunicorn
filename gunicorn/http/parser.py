
import socket

from message import Request
from unreader import SocketUnreader, IterUnreader

class Parser(object):
    def __init__(self, mesg_class, source):
        self.mesg_class = mesg_class
        if isinstance(source, socket.socket):
            self.unreader = SocketUnreader(source)
        else:
            self.unreader = IterUnreader(source)
        self.mesg = None

    def __iter__(self):
        return self
    
    def next(self):
        if self.mesg.should_close():
            raise StopIteration()
        self.discard()
        self.mesg = self.mesg_class(self.unreader)
        if not self.mesg:
            raise StopIteration()
        return self.mesg

    def discard(self):
        if self.mesg is not None:
            data = self.mesg.read(8192)
            while data:
                self.mesg.read(8192)
        self.mesg = None

class RequestParser(Parser):
    def __init__(self, *args, **kwargs):
        super(RequestParser, self).__init__(Request, *args, **kwargs)

