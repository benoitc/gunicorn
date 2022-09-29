# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# We don't need to call super() in __init__ methods of our
# BaseException and Exception classes because we also define
# our own __str__ methods so there is no need to pass 'message'
# to the base class to get a meaningful output from 'str(exc)'.
# pylint: disable=super-init-not-called


class ParseException(Exception):
    pass


class NoMoreData(IOError):
    def __init__(self, buf=None):
        self.buf = buf

    def __str__(self):
        return f"No more data after: {self.buf!r}"


class InvalidRequestLine(ParseException):
    def __init__(self, req):
        self.req = req
        self.code = 400

    def __str__(self):
        return f"Invalid HTTP request line: {self.req!r}"


class InvalidRequestMethod(ParseException):
    def __init__(self, method):
        self.method = method

    def __str__(self):
        return f"Invalid HTTP method: {self.method!r}"


class InvalidHTTPVersion(ParseException):
    def __init__(self, version):
        self.version = version

    def __str__(self):
        return f"Invalid HTTP Version: {self.version!r}"


class InvalidHeader(ParseException):
    def __init__(self, hdr, req=None):
        self.hdr = hdr
        self.req = req

    def __str__(self):
        return f"Invalid HTTP Header: {self.hdr!r}"


class InvalidHeaderName(ParseException):
    def __init__(self, hdr):
        self.hdr = hdr

    def __str__(self):
        return f"Invalid HTTP header name: {self.hdr!r}"


class InvalidChunkSize(IOError):
    def __init__(self, data):
        self.data = data

    def __str__(self):
        return f"Invalid chunk size: {self.data!r}"


class ChunkMissingTerminator(IOError):
    def __init__(self, term):
        self.term = term

    def __str__(self):
        return f"Invalid chunk terminator is not '\\r\\n': {self.term!r}"


class LimitRequestLine(ParseException):
    def __init__(self, size, max_size):
        self.size = size
        self.max_size = max_size

    def __str__(self):
        return f"Request Line is too large ({self.size} > {self.max_size})"


class LimitRequestHeaders(ParseException):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg


class InvalidProxyLine(ParseException):
    def __init__(self, line):
        self.line = line
        self.code = 400

    def __str__(self):
        return f"Invalid PROXY line: {self.line!r}"


class ForbiddenProxyRequest(ParseException):
    def __init__(self, host):
        self.host = host
        self.code = 403

    def __str__(self):
        return f"Proxy request from {self.host!r} not allowed"


class InvalidSchemeHeaders(ParseException):
    def __str__(self):
        return "Contradictory scheme headers"
