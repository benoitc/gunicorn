# -*- coding: utf-8 -
#
# 2009 (c) Benoit Chesneau <benoitc@e-engura.com> 
# 2009 (c) Paul J. Davis <paul.joseph.davis@gmail.com>
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following
# conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.



from errno import EALREADY, EINPROGRESS, EWOULDBLOCK, ECONNRESET, \
     ENOTCONN, ESHUTDOWN, EINTR, EISCONN, EBADF, ECONNABORTED, errorcode
     
import socket

SOCKET_CLOSED = (ECONNRESET, ENOTCONN, ESHUTDOWN)

class IOStream(object):
    
    chunk_size = 4096
    
    def __init__(self, sock):
        self.sock = sock
        self.buf = "" 
        
    def recv(self, buffer_size):
        
        buffer_size = buffer_size or 0
        if self.buf:
            l = len(self.buf)
            if buffer_size > l:
                buffer_size -= l
            else:
                s = self.buf[:buffer_size]
                self.buf = self.buf[buffer_size:]
                return s
        try:
            data =  self.sock.recv(buffer_size)
            s = self.buf + data
            self.buf = ''
            return s
        except socket.error, e:
            if e[0] == EWOULDBLOCK:
                return None
            if e[0] in SOCKET_CLOSED:
                return ''
            raise
           
    def send(self, data):
        return self.sock.send(data)

    def read_until(self, delimiter):
        while True:
            try:
                data = self.recv(self.chunk_size)
            except socket.error, e:
                return
            self.buf = self.buf + data
            
            lb = len(self.buf)
            ld = len(delimiter)
            i = self.buf.find(delimiter)
            if i != -1:
                if i > 0:
                    r = self.buf[:i]
                self.buf = self.buf[i+ ld:]
                return r
