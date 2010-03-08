# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO
    
import urlparse

class BadStatusLine(Exception):
    pass
    
class ParserError(Exception):
    pass

class Parser(object):
    """ HTTP Parser compatible 1.0 & 1.1
    This parser can parse HTTP requests and response.
    """

    def __init__(self, ptype='request', should_close=False):
        self.status_line = ""
        self.status_int = None
        self.reason = ""
        self.status = ""
        self.headers = []
        self.headers_dict = {}
        self.raw_version = "HTTP/1.0"
        self.raw_path = ""
        self.version = (1,0)
        self.method = ""
        self.path = ""
        self.query_string = ""
        self.fragment = ""
        self._content_len = None
        self.start_offset = 0
        self.chunk_size = 0
        self._chunk_eof = False
        self.type = ptype
        self._should_close = should_close
        
    @classmethod
    def parse_response(cls, should_close=False):
        """ Return parser object for response"""
        return cls(ptype='response', should_close=should_close)
        
    @classmethod
    def parse_request(cls):
        """ return parser object for requests """
        return cls(ptype='request')
        
    def filter_headers(self, headers, buf):
        """ take a string as buffer and an header dict 
        (empty or not). It return new position or -1 
        if parsing isn't done. headers dict is updated
        with new headers.
        """
        line = buf.getvalue()
        i = line.find("\r\n\r\n")
        if i != -1:
            r = line[:i]
            pos = i+4
            buf2 = StringIO()
            buf2.write(line[pos:])
            return self.finalize_headers(headers, r, buf2)
        return False
        
    def finalize_headers(self, headers, headers_str, buf2):
        """ parse the headers """
        lines = headers_str.split("\r\n")
                
        # parse first line of headers
        self._first_line(lines.pop(0))
        
        # parse headers. We silently ignore 
        # bad headers' lines
        
        _headers = {}
        hname = ""
        for line in lines:
            if line.startswith('\t') or line.startswith(' '):
                headers[hname] += line.strip()
            else:
                try:
                    hname =self._parse_headerl(_headers, line)
                except ValueError: 
                    # bad headers
                    pass
        self.headers_dict = _headers
        headers.extend(list(_headers.items()))
        self.headers = headers
        self._content_len = int(_headers.get('Content-Length',0))
        
        if self.type == 'request':
            (_, _, self.path, self.query_string, self.fragment) = \
                urlparse.urlsplit(self.raw_path)
        
        return buf2
    
    def _parse_version(self, version):
        self.raw_version = version.strip()
        try:
            major, minor = self.raw_version.split("HTTP/")[1].split(".")
            self.version = (int(major), int(minor))
        except IndexError:
            self.version = (1, 0)
    
    def _first_line(self, line):
        """ parse first line """
        self.status_line = status_line = line.strip()  
        try:
            if self.type == 'response':
                version, self.status = status_line.split(None, 1)
                self._parse_version(version)
                try:
                    self.status_int, self.reason = self.status.split(None, 1)
                except ValueError:
                    self.status_int =  self.status
                self.status_int = int(self.status_int)
            else:
                method, path, version = status_line.split(None, 2)
                self._parse_version(version)
                self.method = method.upper()
                self.raw_path = path
        except ValueError:
            raise BadStatusLine(line)
        
    def _parse_headerl(self, hdrs, line):
        """ parse header line"""
        name, value = line.split(":", 1)
        name = name.strip().title()
        value = value.rsplit("\r\n",1)[0].strip()
        if name in hdrs:
            hdrs[name] = "%s, %s" % (hdrs[name], value)
        else:
            hdrs[name] = value
        return name
      
    @property
    def should_close(self):
        if self._should_close:
            return True
        elif self.headers_dict.get("Connection") == "close":
            return True
        elif self.headers_dict.get("Connection") == "Keep-Alive":
            return False
        elif self.version <= (1, 0):
            return True
        return False
        
    @property
    def is_chunked(self):
        """ is TE: chunked ?"""
        return (self.headers_dict.get('Transfer-Encoding') == "chunked")
        
    @property
    def content_len(self):
        """ return content length as integer or
        None."""
        transfert_encoding = self.headers_dict.get('Transfer-Encoding')
        content_length = self.headers_dict.get('Content-Length')
        if transfert_encoding != "chunked":
            if content_length is None:
                return 0
            return int(content_length)
        else:
            return None
            
    def body_eof(self):
        """do we have all the body ?"""
        if self.is_chunked:
            if self._chunk_eof:
                return True
        elif self._content_len == 0:
            return True
        return False
        
    def read_chunk(self, buf):
        line = buf.getvalue()
        buf2 = StringIO()
        
        if not self.start_offset:
            i = line.find("\r\n")
            if i != -1:
                chunk = line[:i].strip().split(";", 1)
                chunk_size = int(chunk.pop(0), 16)
                self.start_offset = i+2
                self.chunk_size = chunk_size
                
        if self.start_offset:
            if self.chunk_size == 0:
                self._chunk_eof = True
                buf2.write(line[:self.start_offset])
                return '', buf2
            else:
                chunk = line[self.start_offset:self.start_offset+self.chunk_size]
                end_offset = self.start_offset + self.chunk_size + 2
                # we wait CRLF else return None
                if len(buf.getvalue()) >= end_offset:
                    buf2.write(line[end_offset:])
                    self.chunk_size = 0
                    return chunk, buf2
        return '', buf
        
    def trailing_header(self, buf):
        line = buf.getvalue()
        i = line.find("\r\n\r\n")
        return (i != -1)
        
    def filter_body(self, buf):
        """\
        Filter body and return a tuple: (body_chunk, new_buffer)
        Both can be None, and new_buffer is always None if its empty.
        """
        dlen = len(buf.getvalue())
        chunk = ''

        if self.is_chunked:
            try:
                chunk, buf2 = self.read_chunk(buf)
            except Exception, e:
                raise ParserError("chunked decoding error [%s]" % str(e))
            
            if not chunk:
                return '', buf
        else:
            buf2 = StringIO()
            if self._content_len > 0:
                nr = min(dlen, self._content_len)
                chunk = buf.getvalue()[:nr]
                self._content_len -= nr
                
        self.start_offset = 0
        buf2.seek(0, 2)
        return (chunk, buf2)
    
