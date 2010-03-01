# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.


"""
TeeInput replace old FileInput. It use a file 
if size > MAX_BODY or memory. It's now possible to rewind
read or restart etc ... It's based on TeeInput from unicorn.

"""

import os
import StringIO
import tempfile

from gunicorn.util import MAX_BODY, CHUNK_SIZE, read_partial

class TeeInput(object):
    
    def __init__(self, socket, parser, buf, conf):
        self.conf = conf
        self.buf = buf
        self.parser = parser
        self.socket = socket
        self._is_socket = True
        self._len = parser.content_len
        if self._len and self._len < MAX_BODY:
            self.tmp = StringIO.StringIO()
        else:
            self.tmp = tempfile.TemporaryFile(
                            dir=self.conf['tmp_upload_dir'])
            
        if len(buf) > 0:
            chunk, self.buf = parser.filter_body(buf)
            if chunk:
                self.tmp.write(chunk)
            self._finalize()
            self.tmp.seek(0)
        
    @property
    def len(self):
        if self._len: return self._len
        
        if self._is_socket:
            pos = self.tmp.tell()
            while True:
                self.tmp.seek(self._tmp_size())
                if not self._tee(CHUNK_SIZE):
                    break
            self.tmp.seek(pos)
        self._len = self._tmp_size()
        return self._len
        
    def seek(self, offset, whence=0):
        if self._is_socket:
            while True:
                if not self._tee(CHUNK_SIZE):
                    break
        self.tmp.seek(offset, whence)

    def flush(self):
        self.tmp.flush()
        
    def read(self, length=-1):
        """ read """
        if not self._is_socket:
            return self.tmp.read(length)
        
        if length < 0:
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
        if not self._is_socket:
            return self.tmp.readline(size)
        
        orig_size = self._tmp_size()
        if self.tmp.tell() == orig_size:
            if not self._tee(CHUNK_SIZE):
                return ''
            self.tmp.seek(orig_size)
        
        # now we can get line
        line = self.tmp.readline()
        i = line.find("\n")
        if i == -1:
            while True:
                orig_size = self.tmp.tell()
                if not self._tee(CHUNK_SIZE):
                    break
                self.tmp.seek(orig_size)
                line = self.tmp.readline()
                i = line.find("\n")
                if i != -1: 
                    break
                    
        return line
       
    def readlines(self, sizehint=0):
        total = 0
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
        while True:
            chunk, self.buf = self.parser.filter_body(self.buf)
            if chunk:
                self.tmp.write(chunk)
                self.tmp.flush()
                self.tmp.seek(0, os.SEEK_END)
                return chunk
            
            if self.parser.body_eof():
                break
            
            self.buf = read_partial(self.socket, length, self.buf)
        self._finalize()
        return ""
        
    def _finalize(self):
        """ here we wil fetch final trailers
        if any."""
        if self.parser.body_eof():
            del self.buf
            self._is_socket = False
            
    def _tmp_size(self):
        if isinstance(self.tmp, StringIO.StringIO):
            return self.tmp.len
        else:
            return int(os.fstat(self.tmp.fileno())[6])
            
    def _ensure_length(self, buf, length):
        if not buf or not self._len:
            return buf
        while True:
            if len(buf) >= length: 
                break
            data = self._tee(length - len(buf))
            if not data: break
            buf += data
        return buf
