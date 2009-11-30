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

import socket

class TCPServer(socket.socket):
    """class for server-side TCP sockets. 
    This is wrapper around socket.socket class"""
    
    def __init__(self, address, **opts):
        self.address = address
        self.backlog = opts.get('timeout', 1024)
        self.timeout = opts.get('timeout', 300)
        self.reuseaddr = opts.get('reuseaddr', True)
        self.nodelay = opts.get('nodelay', True)
        self.recbuf = opts.get('recbuf', 8192)
        
        socket.socket.__init__(self, socket.AF_INET, socket.SOCK_STREAM)
        
        if self.reuseaddr:
            self.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
             
        if self.nodelay:
            self.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            
        if self.recbuf:
            self.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 
                                self.recbuf)
            
        self.settimeout(self.timeout)
        self.bind(address)
        self.listen()
        
    def listen(self):
        super(TCPServer, self).listen(self.backlog)
       
    def accept(self):
        return super(TCPServer, self).accept()
        
    def accept_nonblock(self):
        self.setblocking(0)
        return self.accept()