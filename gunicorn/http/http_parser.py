# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.


class HttpParser(object):
    
    def __init__(self):
        self._headers = {}
        self.version = None
        self.method = None
        self.path = None
        self._content_len = None
        self.start_offset = 0
        self.chunk_size = 0
        self._chunk_eof = False      
        
    def headers(self, headers, buf):
        """ take a string buff. It return 
        new position or -1 if parsing isn't done.
        headers dict is updated.
        """
        if self._headers:
            return self._headers
        
        # wee could be smarter here
        # by just reading the array, but converting
        # is enough for now
        ld = len("\r\n\r\n")
        i = buf.find("\r\n\r\n")
        if i != -1:
            if i > 0:
                r = buf[:i]
            pos = i+ld
            return self.finalize_headers(headers, r, pos)
        return -1
        
    def finalize_headers(self, headers, headers_str, pos):
        """ parse the headers """
        lines = headers_str.split("\r\n")
                
        # parse first line of headers
        self._first_line(lines.pop(0))
        
        # parse headers. We silently ignore 
        # bad headers' lines
        hname = ""
        for line in lines:
            if line == "\t":
                self._headers[hname] += line.strip()
            else:
                try:
                    hname =self._parse_headerl(line)
                except ValueError: 
                    # bad headers
                    pass
        headers.update(self._headers)
        self._content_len = int(self._headers.get('Content-Length') or 0)
        return pos
    
    def _first_line(self, line):
        """ parse first line """
        method, path, version = line.strip().split(" ")
        self.version = version.strip()
        self.method = method.upper()
        self.path = path
        
    def _parse_headerl(self, line):
        """ parse header line"""
        name, value = line.split(": ", 1)
        name = name.strip()
        self._headers[name] = value.strip()
        return name
      
    @property
    def should_close(self):
        if self._should_close:
            return True
        if self._headers.get("Connection") == "close":
            return True
        if self._headers.get("Connection") == "Keep-Alive":
            return False
        if self.version < "HTTP/1.1":
            return True
        
    @property
    def is_chunked(self):
        """ is TE: chunked ?"""
        transfert_encoding = self._headers.get('Transfer-Encoding', False)
        return (transfert_encoding == "chunked")
        
    @property
    def content_len(self):
        """ return content length as integer or
        None."""
        transfert_encoding = self._headers.get('Transfer-Encoding')
        content_length = self._headers.get('Content-Length')
        if transfert_encoding is None:
            if content_length is None:
                return 0
            return int(content_length)
        else:
            return None
            
    def body_eof(self):
        """do we have all the body ?"""
        if self.is_chunked and self._chunk_eof:
            return True
        if self._content_len == 0:
            return True
        return False
        
    def read_chunk(self, data):
        dlen = len(data)
        if not self.start_offset:
            i = data.find("\n")
            if i != -1:
                chunk = data[:i].strip().split(";", 1)
                chunk_size = int(line.pop(0), 16)
                self.start_offset = i+1
                self.chunk_size = chunk_size
        else:
            buf = self.data[self.start_offset:]
            
            end_offset = chunk_size + 2
            # we wait CRLF else return None
            if len(buf) == end_offset:
                if chunk_size <= 0:
                    self._chunk_eof = True
                    # we put data 
                    return '', data[:end_offset]
                self.chunk_size = 0
                return buf[chunk_size:], data[:end_offset]
        return '', data
        
    def trailing_header(self, data):
        i = data.find("\r\n\r\n")
        return (i != -1)
        
    def filter_body(self, data):
        """ filter body and return a tuple:
        body_chunk, new_buffer. They could be None.
        new_fubber is always None if it's empty.
        
        """
        dlen = len(data)
        chunk = ''
        if self.is_chunked:
            chunk, data = self.read_chunk(data)
            if not chunk:
                return '', data
        else:
            if self._content_len > 0:
                nr = min(dlen, self._content_len)
                chunk = data[:nr]
                self._content_len -= nr
                data = ''
                
        self.start_offset = 0
        return (chunk, data)
