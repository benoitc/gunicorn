# -*- coding: utf-8 -
#
# 2009 (c) Benoit Chesneau <benoitc@e-engura.com> 
# 2009 (c) Paul J. Davis <paul.joseph.davis@gmail.com>
#
# Permission to use, copy, modify, and distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.



from errno import EALREADY, EINPROGRESS, EWOULDBLOCK, ECONNRESET, \
     ENOTCONN, ESHUTDOWN, EINTR, EISCONN, EBADF, ECONNABORTED, errorcode
     
import socket

SOCKET_CLOSED = (ECONNRESET, ENOTCONN, ESHUTDOWN)

class IOStream(object):
    
    chunk_size = 4096
    
    def __init__(self, sock):
        self.sock = sock.dup()
        self.sock.setblocking(0)
        self.buf = "" 
        
    def recv(self, buffer_size):
        try:
            return self.sock.recv(buffer_size)
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
