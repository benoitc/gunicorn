# Copyright 2009 Paul J. Davis <paul.joseph.davis@gmail.com>
#
# This file is part of the pywebmachine package released
# under the MIT license.

import inspect
import os
import random

from gunicorn._compat import execfile_
from gunicorn.config import Config
from gunicorn.http.parser import RequestParser
from gunicorn.util import split_request_uri
from gunicorn import six

dirname = os.path.dirname(__file__)
random.seed()


def uri(data):
    ret = {"raw": data}
    parts = split_request_uri(data)
    ret["scheme"] = parts.scheme or ''
    ret["host"] = parts.netloc.rsplit(":", 1)[0] or None
    ret["port"] = parts.port or 80
    ret["path"] = parts.path or ''
    ret["query"] = parts.query or ''
    ret["fragment"] = parts.fragment or ''
    return ret


def load_py(fname):
    config = globals().copy()
    config["uri"] = uri
    config["cfg"] = Config()
    execfile_(fname, config)
    return config


class request(object):
    def __init__(self, fname, expect):
        self.fname = fname
        self.name = os.path.basename(fname)

        self.expect = expect
        if not isinstance(self.expect, list):
            self.expect = [self.expect]

        with open(self.fname, 'rb') as handle:
            self.data = handle.read()
        self.data = self.data.replace(b"\n", b"").replace(b"\\r\\n", b"\r\n")
        self.data = self.data.replace(b"\\0", b"\000")

    # Functions for sending data to the parser.
    # These functions mock out reading from a
    # socket or other data source that might
    # be used in real life.

    def send_all(self):
        yield self.data

    def send_lines(self):
        lines = self.data
        pos = lines.find(b"\r\n")
        while pos > 0:
            yield lines[:pos+2]
            lines = lines[pos+2:]
            pos = lines.find(b"\r\n")
        if lines:
            yield lines

    def send_bytes(self):
        for d in self.data:
            if six.PY3:
                yield bytes([d])
            else:
                yield d

    def send_random(self):
        maxs = round(len(self.data) / 10)
        read = 0
        while read < len(self.data):
            chunk = random.randint(1, maxs)
            yield self.data[read:read+chunk]
            read += chunk

    def send_special_chunks(self):
        """Meant to test the request line length check.

        Sends the request data in two chunks, one having a
        length of 1 byte, which ensures that no CRLF is included,
        and a second chunk containing the rest of the request data.

        If the request line length check is not done properly,
        testing the ``tests/requests/valid/099.http`` request
        fails with a ``LimitRequestLine`` exception.

        """
        chunk = self.data[:1]
        read = 0
        while read < len(self.data):
            yield self.data[read:read+len(chunk)]
            read += len(chunk)
            chunk = self.data[read:]

    # These functions define the sizes that the
    # read functions will read with.

    def size_all(self):
        return -1

    def size_bytes(self):
        return 1

    def size_small_random(self):
        return random.randint(1, 4)

    def size_random(self):
        return random.randint(1, 4096)

    # Match a body against various ways of reading
    # a message. Pass in the request, expected body
    # and one of the size functions.

    def szread(self, func, sizes):
        sz = sizes()
        data = func(sz)
        if sz >= 0 and len(data) > sz:
            raise AssertionError("Read more than %d bytes: %s" % (sz, data))
        return data

    def match_read(self, req, body, sizes):
        data = self.szread(req.body.read, sizes)
        count = 1000
        while body:
            if body[:len(data)] != data:
                raise AssertionError("Invalid body data read: %r != %r" % (
                                        data, body[:len(data)]))
            body = body[len(data):]
            data = self.szread(req.body.read, sizes)
            if not data:
                count -= 1
            if count <= 0:
                raise AssertionError("Unexpected apparent EOF")

        if body:
            raise AssertionError("Failed to read entire body: %r" % body)
        elif data:
            raise AssertionError("Read beyond expected body: %r" % data)
        data = req.body.read(sizes())
        if data:
            raise AssertionError("Read after body finished: %r" % data)

    def match_readline(self, req, body, sizes):
        data = self.szread(req.body.readline, sizes)
        count = 1000
        while body:
            if body[:len(data)] != data:
                raise AssertionError("Invalid data read: %r" % data)
            if b'\n' in data[:-1]:
                raise AssertionError("Embedded new line: %r" % data)
            body = body[len(data):]
            data = self.szread(req.body.readline, sizes)
            if not data:
                count -= 1
            if count <= 0:
                raise AssertionError("Apparent unexpected EOF")
        if body:
            raise AssertionError("Failed to read entire body: %r" % body)
        elif data:
            raise AssertionError("Read beyond expected body: %r" % data)
        data = req.body.readline(sizes())
        if data:
            raise AssertionError("Read data after body finished: %r" % data)

    def match_readlines(self, req, body, sizes):
        """\
        This skips the sizes checks as we don't implement it.
        """
        data = req.body.readlines()
        for line in data:
            if b'\n' in line[:-1]:
                raise AssertionError("Embedded new line: %r" % line)
            if line != body[:len(line)]:
                raise AssertionError("Invalid body data read: %r != %r" % (
                                                    line, body[:len(line)]))
            body = body[len(line):]
        if body:
            raise AssertionError("Failed to read entire body: %r" % body)
        data = req.body.readlines(sizes())
        if data:
            raise AssertionError("Read data after body finished: %r" % data)

    def match_iter(self, req, body, sizes):
        """\
        This skips sizes because there's its not part of the iter api.
        """
        for line in req.body:
            if b'\n' in line[:-1]:
                raise AssertionError("Embedded new line: %r" % line)
            if line != body[:len(line)]:
                raise AssertionError("Invalid body data read: %r != %r" % (
                                                    line, body[:len(line)]))
            body = body[len(line):]
        if body:
            raise AssertionError("Failed to read entire body: %r" % body)
        try:
            data = six.next(iter(req.body))
            raise AssertionError("Read data after body finished: %r" % data)
        except StopIteration:
            pass

    # Construct a series of test cases from the permutations of
    # send, size, and match functions.

    def gen_cases(self, cfg):
        def get_funs(p):
            return [v for k, v in inspect.getmembers(self) if k.startswith(p)]
        senders = get_funs("send_")
        sizers = get_funs("size_")
        matchers = get_funs("match_")
        cfgs = [
            (mt, sz, sn)
            for mt in matchers
            for sz in sizers
            for sn in senders
        ]

        ret = []
        for (mt, sz, sn) in cfgs:
            if hasattr(mt, 'funcname'):
                mtn = mt.func_name[6:]
                szn = sz.func_name[5:]
                snn = sn.func_name[5:]
            else:
                mtn = mt.__name__[6:]
                szn = sz.__name__[5:]
                snn = sn.__name__[5:]

            def test_req(sn, sz, mt):
                self.check(cfg, sn, sz, mt)
            desc = "%s: MT: %s SZ: %s SN: %s" % (self.name, mtn, szn, snn)
            test_req.description = desc
            ret.append((test_req, sn, sz, mt))
        return ret

    def check(self, cfg, sender, sizer, matcher):
        cases = self.expect[:]
        p = RequestParser(cfg, sender())
        for req in p:
            self.same(req, sizer, matcher, cases.pop(0))
        assert not cases

    def same(self, req, sizer, matcher, exp):
        assert req.method == exp["method"]
        assert req.uri == exp["uri"]["raw"]
        assert req.path == exp["uri"]["path"]
        assert req.query == exp["uri"]["query"]
        assert req.fragment == exp["uri"]["fragment"]
        assert req.version == exp["version"]
        assert req.headers == exp["headers"]
        matcher(req, exp["body"], sizer)
        assert req.trailers == exp.get("trailers", [])


class badrequest(object):
    def __init__(self, fname):
        self.fname = fname
        self.name = os.path.basename(fname)

        with open(self.fname) as handle:
            self.data = handle.read()
        self.data = self.data.replace("\n", "").replace("\\r\\n", "\r\n")
        self.data = self.data.replace("\\0", "\000")
        self.data = self.data.encode('latin1')

    def send(self):
        maxs = round(len(self.data) / 10)
        read = 0
        while read < len(self.data):
            chunk = random.randint(1, maxs)
            yield self.data[read:read+chunk]
            read += chunk

    def check(self, cfg):
        p = RequestParser(cfg, self.send())
        six.next(p)
