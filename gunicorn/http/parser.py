
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
        # Stop if HTTP dictates a stop.
        if self.mesg and self.mesg.should_close():
            raise StopIteration()
        
        # Discard any unread body of the previous message
        if self.mesg:
            data = self.mesg.body.read(8192)
            while data:
                data = mesg.body.read(8192)
        
        # Parse the next request
        self.mesg = self.mesg_class(self.unreader)
        if not self.mesg:
            raise StopIteration()
        return self.mesg

class RequestParser(Parser):
    def __init__(self, *args, **kwargs):
        super(RequestParser, self).__init__(Request, *args, **kwargs)

