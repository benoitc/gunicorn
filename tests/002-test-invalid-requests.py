# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import t
import treq

import glob
import os
from nose.tools import raises

dirname = os.path.dirname(__file__)
reqdir = os.path.join(dirname, "requests", "invalid")


def test_http_parser():
    for fname in glob.glob(os.path.join(reqdir, "*.http")):
        env = treq.load_py(os.path.splitext(fname)[0] + ".py")
        expect = env['request']
        cfg = env['cfg']
        req = treq.badrequest(fname)

        @raises(expect)
        def check(fname):
            return req.check(cfg)

        yield check, fname # fname is pass so that we know which test failed
