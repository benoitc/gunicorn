# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import t

import functools
import os
import sys

from gunicorn import config
from gunicorn.app.base import Application
from gunicorn.workers.sync import SyncWorker

dirname = os.path.dirname(__file__)
def cfg_module():
    return 'config.test_cfg'
def cfg_file():
    return os.path.join(dirname, "config", "test_cfg.py")
def paster_ini():
    return os.path.join(dirname, "..", "examples", "frameworks", "pylonstest", "nose.ini")

class AltArgs(object):
    def __init__(self, args=None):
        self.args = args or []
        self.orig = sys.argv

    def __enter__(self):
        sys.argv = self.args

    def __exit__(self, exc_type, exc_inst, traceback):
        sys.argv = self.orig

class NoConfigApp(Application):
    def __init__(self):
        super(NoConfigApp, self).__init__("no_usage", prog="gunicorn_test")

    def init(self, parser, opts, args):
        pass

    def load(self):
        pass


def test_defaults():
    c = config.Config()
    for s in config.KNOWN_SETTINGS:
        t.eq(c.settings[s.name].validator(s.default),
             c.settings[s.name].get())

def test_property_access():
    c = config.Config()
    for s in config.KNOWN_SETTINGS:
        getattr(c, s.name)

    # Class was loaded
    t.eq(c.worker_class, SyncWorker)

    # Workers defaults to 1
    t.eq(c.workers, 1)
    c.set("workers", 3)
    t.eq(c.workers, 3)

    # Address is parsed
    t.eq(c.address, [("127.0.0.1", 8000)])

    # User and group defaults
    t.eq(os.geteuid(), c.uid)
    t.eq(os.getegid(), c.gid)

    # Proc name
    t.eq("gunicorn", c.proc_name)

    # Not a config property
    t.raises(AttributeError, getattr, c, "foo")
    # Force to be not an error
    class Baz(object):
        def get(self):
            return 3.14
    c.settings["foo"] = Baz()
    t.eq(c.foo, 3.14)

    # Attempt to set a cfg not via c.set
    t.raises(AttributeError, setattr, c, "proc_name", "baz")

    # No setting for name
    t.raises(AttributeError, c.set, "baz", "bar")

def test_bool_validation():
    c = config.Config()
    t.eq(c.preload_app, False)
    c.set("preload_app", True)
    t.eq(c.preload_app, True)
    c.set("preload_app", "true")
    t.eq(c.preload_app, True)
    c.set("preload_app", "false")
    t.eq(c.preload_app, False)
    t.raises(ValueError, c.set, "preload_app", "zilch")
    t.raises(TypeError, c.set, "preload_app", 4)

def test_pos_int_validation():
    c = config.Config()
    t.eq(c.workers, 1)
    c.set("workers", 4)
    t.eq(c.workers, 4)
    c.set("workers", "5")
    t.eq(c.workers, 5)
    c.set("workers", "0xFF")
    t.eq(c.workers, 255)
    c.set("workers", True)
    t.eq(c.workers, 1) # Yes. That's right...
    t.raises(ValueError, c.set, "workers", -21)
    t.raises(TypeError, c.set, "workers", c)

def test_str_validation():
    c = config.Config()
    t.eq(c.proc_name, "gunicorn")
    c.set("proc_name", " foo ")
    t.eq(c.proc_name, "foo")
    t.raises(TypeError, c.set, "proc_name", 2)

def test_str_to_list_validation():
    c = config.Config()
    t.eq(c.forwarded_allow_ips, ["127.0.0.1"])
    c.set("forwarded_allow_ips", "127.0.0.1,192.168.0.1")
    t.eq(c.forwarded_allow_ips, ["127.0.0.1", "192.168.0.1"])
    c.set("forwarded_allow_ips", "")
    t.eq(c.forwarded_allow_ips, [])
    c.set("forwarded_allow_ips", None)
    t.eq(c.forwarded_allow_ips, [])
    t.raises(TypeError, c.set, "forwarded_allow_ips", 1)

def test_callable_validation():
    c = config.Config()
    def func(a, b):
        pass
    c.set("pre_fork", func)
    t.eq(c.pre_fork, func)
    t.raises(TypeError, c.set, "pre_fork", 1)
    t.raises(TypeError, c.set, "pre_fork", lambda x: True)

def test_callable_validation_for_string():
    from os.path import isdir as testfunc
    t.eq(
        config.validate_callable(-1)("os.path.isdir"),
        testfunc
    )

    # invalid values tests
    t.raises(
        TypeError,
        config.validate_callable(-1), ""
    )
    t.raises(
        TypeError,
        config.validate_callable(-1), "os.path.not_found_func"
    )
    t.raises(
        TypeError,
        config.validate_callable(-1), "notfoundmodule.func"
    )


def test_cmd_line():
    with AltArgs(["prog_name", "-b", "blargh"]):
        app = NoConfigApp()
        t.eq(app.cfg.bind, ["blargh"])
    with AltArgs(["prog_name", "-w", "3"]):
        app = NoConfigApp()
        t.eq(app.cfg.workers, 3)
    with AltArgs(["prog_name", "--preload"]):
        app = NoConfigApp()
        t.eq(app.cfg.preload_app, True)

def test_app_config():
    with AltArgs():
        app = NoConfigApp()
    for s in config.KNOWN_SETTINGS:
        t.eq(app.cfg.settings[s.name].validator(s.default),
             app.cfg.settings[s.name].get())

def test_load_config():
    with AltArgs(["prog_name", "-c", cfg_file()]):
        app = NoConfigApp()
    t.eq(app.cfg.bind, ["unix:/tmp/bar/baz"])
    t.eq(app.cfg.workers, 3)
    t.eq(app.cfg.proc_name, "fooey")

def test_load_config_module():
    with AltArgs(["prog_name", "-c", cfg_module()]):
        app = NoConfigApp()
    t.eq(app.cfg.bind, ["unix:/tmp/bar/baz"])
    t.eq(app.cfg.workers, 3)
    t.eq(app.cfg.proc_name, "fooey")

def test_cli_overrides_config():
    with AltArgs(["prog_name", "-c", cfg_file(), "-b", "blarney"]):
        app = NoConfigApp()
        t.eq(app.cfg.bind, ["blarney"])
        t.eq(app.cfg.proc_name, "fooey")

def test_cli_overrides_config_module():
    with AltArgs(["prog_name", "-c", cfg_module(), "-b", "blarney"]):
        app = NoConfigApp()
        t.eq(app.cfg.bind, ["blarney"])
        t.eq(app.cfg.proc_name, "fooey")

def test_default_config_file():
    default_config = os.path.join(os.path.abspath(os.getcwd()), 
                                                  'gunicorn.conf.py')
    with open(default_config, 'w+') as default:
        default.write("bind='0.0.0.0:9090'")
    
    t.eq(config.get_default_config_file(), default_config)

    with AltArgs(["prog_name"]):
        app = NoConfigApp()
        t.eq(app.cfg.bind, ["0.0.0.0:9090"])

    os.unlink(default_config)

def test_post_request():
    c = config.Config()

    def post_request_4(worker, req, environ, resp):
        return 4

    def post_request_3(worker, req, environ):
        return 3

    def post_request_2(worker, req):
        return 2

    c.set("post_request", post_request_4)
    t.eq(4, c.post_request(1, 2, 3, 4))

    c.set("post_request", post_request_3)
    t.eq(3, c.post_request(1, 2, 3, 4))

    c.set("post_request", post_request_2)
    t.eq(2, c.post_request(1, 2, 3, 4))


def test_nworkers_changed():
    c = config.Config()
    def nworkers_changed_3(server, new_value, old_value):
        return 3

    c.set("nworkers_changed", nworkers_changed_3)
    t.eq(3, c.nworkers_changed(1, 2, 3))
