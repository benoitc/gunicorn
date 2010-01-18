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

from gunicorn.util import MAX_BODY, CHUNK_SIZE

class TeeInput(object):
    
    def __init__(self, socket, parser, buf):
        self.buf = buf
        self.parser = parser
        self.socket = socket.dup()
        self._len = parser.content_len
        if self._len and self._len < MAX_BODY:
            self.tmp = StringIO.StringIO()
        else:
            self.tmp = tempfile.TemporaryFile()
            
        if len(buf) > 0:
            chunk, self.buf = parser.filter_body(buf)
            print chunk
            if chunk:
                self.tmp.write(chunk)
                self.tmp.seek(0)
            self._finalize()
        
    @property
    def len(self):
        if self._len: return self._len
        if self.socket:
            pos = self.tmp.tell() 
            while True:
                if not self._tee(CHUNK_SIZE):
                    break
            self.tmp.seek(pos)
        self._len = self._tmp_size()
        return self._len

    def flush(self):
        self.tmp.flush()
        
    def read(self, length=None):
        """ read """
        if not self.socket:
            return self.tmp.read(length)
        
        if length is None:
            r = self.tmp.read() or ""
            while True:
                chunk = self._tee(CHUNK_SIZE)
                if not chunk: break
                r += chunk
            return r
        else:
            diff = self._tmp_size() - self.tmp.tell()
            if not diff:
                return self._ensure_length(self._tee(length), length)
            else:
                l = min(diff, length)
                return self._ensure_length(self.tmp.read(l), length)
                
    def readline(self, size=-1):
        if not self.socket:
            return self.tmp.readline(size)
        
        orig_size = self._tmp_size()
        if self.tmp.tell() == orig_size:
            if not self._tee(CHUNK_SIZE):
                return ''
            self.tmp.seek(orig_size)
        
        # now we can get line
        line = self.tmp.readline()
        if size > 0 and len(line) < size:
            self.tmp.seek(orig_size)
            while True:
                if not self._tee(CHUNK_SIZE):
                    self.tmp.seek(orig_size)
                    return self.temp.readline(size)
        return line
       
    def readlines(self, sizehints=0):
        lines = []
        line = self.readline()
        while line:
            lines.append(line)
            total += len(line)
            if 0 < sizehint <= total:
                break
            line = self.readline()
        return lines
    
    def next(self):
        r = self.readline()
        if not r:
            raise StopIteration
        return r
    __next__ = next
    
    def __iter__(self):
        return self    

    def _tee(self, length):
        """ fetch partial body"""
        while not self.parser.body_eof():
            data = read_partial(self.socket, length)
            self.buf += data
            chunk, self.buf = self.parser.filter_body(self.buf)
            if chunk:
                self.tmp.write(chunk)
                self.tmp.seek(0, os.SEEK_END)
                return chunk
        self._finalize()
        return ""
        
    def _finalize(self):
        """ here we wil fetch final trailers
        if any."""
        if self.parser.body_eof():
            # handle trailing headers
            if self.parser.is_chunked:
                while not self.parser.trailing_header(self.buf):
                    data = read_partial(self.socket, CHUNK_SIZE)
                    if not data: break
                    self.buf += data
            del self.buf
            self.socket = None
            
    def _tmp_size(self):
        if isinstance(self.tmp, StringIO.StringIO):
            return self.tmp.len
        else:
            return int(os.fstat(self.tmp.fileno())[6])
            
    def _ensure_length(buf, length):
        if not buf or not self._len:
            return buf
        while len(buf) < length and self.len != self.tmp.pos():
            buf += self._tee(length - len(buf))
        return buf