# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import t
import treq

import glob
import os
dirname = os.path.dirname(__file__)
reqdir = os.path.join(dirname, "requests", "valid")

def a_case(fname):
    expect = treq.load_py(os.path.splitext(fname)[0] + ".py")
    req = treq.request(fname, expect)
    for case in req.gen_cases():
        case[0](*case[1:])

def test_http_parser():
    for fname in glob.glob(os.path.join(reqdir, "*.http")):
        if os.getenv("GUNS_BLAZING"):
            expect = treq.load_py(os.path.splitext(fname)[0] + ".py")
            req = treq.request(fname, expect)
            for case in req.gen_cases():
                yield case
        else:
            yield (a_case, fname)
