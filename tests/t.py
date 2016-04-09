# -*- coding: utf-8 -
# Copyright 2009 Paul J. Davis <paul.joseph.davis@gmail.com>
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import os
import tempfile

dirname = os.path.dirname(__file__)

from gunicorn.http.parser import RequestParser
from gunicorn.config import Config
from gunicorn.six import BytesIO

def data_source(fname):
    buf = BytesIO()
    with open(fname) as handle:
        for line in handle:
            line = line.rstrip("\n").replace("\\r\\n", "\r\n")
            buf.write(line.encode('latin1'))
        return buf

class request(object):
    def __init__(self, name):
        self.fname = os.path.join(dirname, "requests", name)

    def __call__(self, func):
        def run():
            src = data_source(self.fname)
            func(src, RequestParser(src))
        run.func_name = func.func_name
        return run


class FakeSocket(object):

    def __init__(self, data):
        self.tmp = tempfile.TemporaryFile()
        if data:
            self.tmp.write(data.getvalue())
            self.tmp.flush()
            self.tmp.seek(0)

    def fileno(self):
        return self.tmp.fileno()

    def len(self):
        return self.tmp.len

    def recv(self, length=None):
        return self.tmp.read(length)

    def recv_into(self, buf, length):
        tmp_buffer = self.tmp.read(length)
        v = len(tmp_buffer)
        for i, c in enumerate(tmp_buffer):
            buf[i] = c
        return v

    def send(self, data):
        self.tmp.write(data)
        self.tmp.flush()

    def seek(self, offset, whence=0):
        self.tmp.seek(offset, whence)


class http_request(object):
    def __init__(self, name):
        self.fname = os.path.join(dirname, "requests", name)

    def __call__(self, func):
        def run():
            fsock = FakeSocket(data_source(self.fname))
            req = Request(Config(), fsock, ('127.0.0.1', 6000), ('127.0.0.1', 8000))
            func(req)
        run.func_name = func.func_name
        return run
