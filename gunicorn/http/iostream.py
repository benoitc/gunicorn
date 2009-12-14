# -*- coding: utf-8 -*-
#
# Copyright 2008,2009 Benoit Chesneau <benoitc@e-engura.org>
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at#
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from errno import EALREADY, EINPROGRESS, EWOULDBLOCK, ECONNRESET, \
     ENOTCONN, ESHUTDOWN, EINTR, EISCONN, EBADF, ECONNABORTED, errorcode
     
import socket

class IOStream(object):
    
    chunk_size = 4096
    
    def __init__(self, sock):
        self.sock = sock
        
        self.buf = "" 
        

    def recv(self, buffer_size):
        try:
            data = self.sock.recv(buffer_size)
            if not data:
                # we should handle close here
                return ''
            return data
        except socket.error, e:
            if e.args[0] in (errno.ECONNRESET, errno.ENOTCONN, 
                            errno.ESHUTDOWN, errno.ECONNABORTED):
                # we should handle close here
                return ''
            raise
            
    def send(self, data):
        try:
            rst = self.sock.send(data)
            return rst
        except socket.error, e:
            if e.args[0] == EWOULDBLOCK:
                return 0
            elif e.args[0] in (errno.ECONNRESET, errno.ENOTCONN, 
                            errno.ESHUTDOWN, errno.ECONNABORTED):
                # we should handle close here
                
                return 0
            else:
                raise

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
