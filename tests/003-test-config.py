# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from nose.plugins.skip import SkipTest

import t

import functools
import os
import sys

from gunicorn import config
from gunicorn.app.base import Application
from gunicorn.workers.sync import SyncWorker

dirname = os.path.dirname(__file__)
def cfg_file():
    return os.path.join(dirname, "config", "test_cfg.py")
def paster_ini():
    return os.path.join(dirname, "..", "examples", "pylonstest", "nose.ini")

def PasterApp():
    try:
        from paste.deploy import loadapp, loadwsgi
    except ImportError:
        raise SkipTest()
    from gunicorn.app.pasterapp import PasterApplication
    return PasterApplication("no_usage")

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
        super(NoConfigApp, self).__init__("no_usage")
    
    def init(self, parser, opts, args):
        pass
    
    def load(self):
        pass


def test_defaults():
    c = config.Config()
    for s in config.KNOWN_SETTINGS:
        t.eq(s.default, c.settings[s.name].get())

def test_property_access():
    c = config.Config()
    for s in config.KNOWN_SETTINGS:
        getattr(c, s.name)
    
    # Class was loaded
    t.eq(c.worker_class, SyncWorker)
    
    # Debug affects workers
    t.eq(c.workers, 1)
    c.set("workers", 3)
    t.eq(c.workers, 3)
    c.set("debug", True)
    t.eq(c.workers, 1)
    
    # Address is parsed
    t.eq(c.address, ("127.0.0.1", 8000))
    
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
    t.eq(c.debug, False)
    c.set("debug", True)
    t.eq(c.debug, True)
    c.set("debug", "true")
    t.eq(c.debug, True)
    c.set("debug", "false")
    t.eq(c.debug, False)
    t.raises(ValueError, c.set, "debug", "zilch")
    t.raises(TypeError, c.set, "debug", 4)

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

def test_callable_validation():
    c = config.Config()
    def func(a, b):
        pass
    c.set("pre_fork", func)
    t.eq(c.pre_fork, func)
    t.raises(TypeError, c.set, "pre_fork", 1)
    t.raises(TypeError, c.set, "pre_fork", lambda x: True)

def test_cmd_line():
    with AltArgs(["prog_name", "-b", "blargh"]):
        app = NoConfigApp()
        t.eq(app.cfg.bind, "blargh")
    with AltArgs(["prog_name", "-w", "3"]):
        app = NoConfigApp()
        t.eq(app.cfg.workers, 3)
    with AltArgs(["prog_name", "-d"]):
        app = NoConfigApp()
        t.eq(app.cfg.debug, True)

def test_app_config():
    with AltArgs():
        app = NoConfigApp()
    for s in config.KNOWN_SETTINGS:
        t.eq(s.default, app.cfg.settings[s.name].get())

def test_load_config():
    with AltArgs(["prog_name", "-c", cfg_file()]):
        app = NoConfigApp()
    t.eq(app.cfg.bind, "unix:/tmp/bar/baz")
    t.eq(app.cfg.workers, 3)
    t.eq(app.cfg.proc_name, "fooey")
    
def test_cli_overrides_config():
    with AltArgs(["prog_name", "-c", cfg_file(), "-b", "blarney"]):
        app = NoConfigApp()
        t.eq(app.cfg.bind, "blarney")
        t.eq(app.cfg.proc_name, "fooey")

def test_paster_config():
    with AltArgs(["prog_name", paster_ini()]):
        app = PasterApp()
        t.eq(app.cfg.bind, "192.168.0.1:80")
        t.eq(app.cfg.proc_name, "brim")
        t.eq("ignore_me" in app.cfg.settings, False)

def test_cfg_over_paster():
    with AltArgs(["prog_name", "-c", cfg_file(), paster_ini()]):
        app = PasterApp()
        t.eq(app.cfg.bind, "unix:/tmp/bar/baz")
        t.eq(app.cfg.proc_name, "fooey")
        t.eq(app.cfg.default_proc_name, "blurgh")

def test_cli_cfg_paster():
    with AltArgs(["prog_name", "-c", cfg_file(), "-b", "whee", paster_ini()]):
        app = PasterApp()
        t.eq(app.cfg.bind, "whee")
        t.eq(app.cfg.proc_name, "fooey")
        t.eq(app.cfg.default_proc_name, "blurgh")
