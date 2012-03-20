# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

class ParseException(Exception):
    pass

class NoMoreData(ParseException, StopIteration):
    def __init__(self, buf=None):
        self.buf = buf
    def __str__(self):
        return "No more data after: %r" % self.buf

class InvalidRequestLine(ParseException):
    def __init__(self, req):
        self.req = req
        self.code = 400

    def __str__(self):
        return "Invalid HTTP request line: %r" % self.req

class InvalidRequestMethod(ParseException):
    def __init__(self, method):
        self.method = method

    def __str__(self):
        return "Invalid HTTP method: %r" % self.method

class InvalidHTTPVersion(ParseException):
    def __init__(self, version):
        self.version = version

    def __str__(self):
        return "Invalid HTTP Version: %s" % self.version

class InvalidHeader(ParseException):
    def __init__(self, hdr):
        self.hdr = hdr

    def __str__(self):
        return "Invalid HTTP Header: %r" % self.hdr

class InvalidHeaderName(ParseException):
    def __init__(self, hdr):
        self.hdr = hdr

    def __str__(self):
        return "Invalid HTTP header name: %r" % self.hdr

class InvalidChunkSize(ParseException):
    def __init__(self, data):
        self.data = data

    def __str__(self):
        return "Invalid chunk size: %r" % self.data

class ChunkMissingTerminator(ParseException):
    def __init__(self, term):
        self.term = term

    def __str__(self):
        return "Invalid chunk terminator is not '\\r\\n': %r" % self.term


class LimitRequestLine(ParseException):
    def __init__(self, size, max_size):
        self.size = size
        self.max_size = max_size

    def __str__(self):
        return "Request Line is too large (%s > %s)" % (self.size, self.max_size)

class LimitRequestHeaders(ParseException):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg
