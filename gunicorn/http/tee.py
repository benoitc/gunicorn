# -*- coding: utf-8 -
#
# 2010 (c) Benoit Chesneau <benoitc@e-engura.com> 
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

"""
TeeInput replace old FileInput. It use a file 
if size > MAX_BODY or memory. It's now possible to rewind
read or restart etc ... It's based on TeeInput from unicorn.

"""


import os
import StringIO
import tempfile
from ctypes import create_string_buffer

from gunicorn.util import MAX_BODY, CHUNK_SIZE

class TeeInput(object):
    
    def __init__(self, socket, parser, buf, remain):
        self.buf = buf
        self.remain = remain
        self.parser = parser
        self.socket = socket
        self._len = parser.content_length
        if self._len and self._len < MAX_BODY:
            self.tmp = StringIO.StringIO()
        else:
            self.tmp = tempfile.TemporaryFile()
        self.buf2 = create_string_buffer(tmp)
        if len(buf) > 0:
            parser.filter_body(self.buf2, buf)
            self._finalize()
            self.tmp.write(self.buf2)
            self.tmp.seek(0)
        
    @property
    def len(self):
        if self._len: return self._len
        if self.remain:
            pos = self.tmp.tell() 
            while True:
                if not self._tee(self.remain, self.buf2):
                    break
            self.tmp.seek(pos)
        self._len = self._tmp_size()
        return self._len


    def read(self, length=None):
        """ read """
        if not self.remain:
            return self.tmp.read(length)
        
        if not length:
            r = self.tmp.read() or ""
            while self._tee(self.remain, self.buf2):
                r += self.buf2.value
            return r
        else:
            r = self.buf2
            diff = self._tmp_size() - self.tmp.tell()
            if not diff:
                return self._ensure_length(self._tee(self.remain, r), self.remain)
            else:
                length = min(diff, self.remain)
                return self._ensure_length(self._tee(length, r), length)
                
    def readline(self, amt=-1):
        pass
        
    def readlines(self, sizehints=0):
        pass
        
    def __next__(self):
        r = self.readline()
        if not r:
            raise StopIteration
        return r
    next = __next__
    
    def __iter__(self):
        return self    

    def _tee(self, length, dst):
        """ fetch partial body"""
        while not self.parser.body_eof() and self.remain:
            data = create_string_buffer(length)
            length -= self.socket.recv_into(data, length)
            self.remain = length
            if self.parser.filter_body(dst, data):
                self.tmp.write(dst.value)
                self.tmp.seek(0, os.SEEK_END)
                return dst
        self._finalize()
        return ""
        
    def _finalize(self):
        """ here we wil fetch final trailers
        if any."""
            
            
    def _tmp_size(self):
        if isinstance(self.tmp, StringIO.StringIO):
            return self.tmp.len
        else:
            return int(os.fstat(self.tmp.fileno())[6])
            
    def _ensure_length(buf, length):
        if not buf or not self._len:
            return buf
        while len(buf) < length and self.len != self.tmp.pos():
            buf += self._tee(length - len(buf), self.buf2)
            
        return buf