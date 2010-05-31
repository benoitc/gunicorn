# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import t
import treq

import glob
import os
dirname = os.path.dirname(__file__)
reqdir = os.path.join(dirname, "requests")

def load_py(fname):
    config = globals().copy()
    config["uri"] = treq.uri
    execfile(fname, config)
    return config["request"]

def test_http_parser():
    for fname in glob.glob(os.path.join(reqdir, "*.http")):
        expect = load_py(os.path.splitext(fname)[0] + ".py")
        req = treq.request(fname, expect)
        for case in req.gen_cases():
            yield case
