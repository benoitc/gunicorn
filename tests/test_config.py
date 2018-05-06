# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import os
import sys

import pytest

from gunicorn import config
from gunicorn.app.base import Application
from gunicorn.errors import ConfigError
from gunicorn.workers.sync import SyncWorker
from gunicorn import glogging
from gunicorn.instrument import statsd

dirname = os.path.dirname(__file__)
def cfg_module():
    return 'config.test_cfg'
def alt_cfg_module():
    return 'config.test_cfg_alt'
def cfg_file():
    return os.path.join(dirname, "config", "test_cfg.py")
def alt_cfg_file():
    return os.path.join(dirname, "config", "test_cfg_alt.py")
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
        assert c.settings[s.name].validator(s.default) == c.settings[s.name].get()


def test_property_access():
    c = config.Config()
    for s in config.KNOWN_SETTINGS:
        getattr(c, s.name)

    # Class was loaded
    assert c.worker_class == SyncWorker

    # logger class was loaded
    assert c.logger_class == glogging.Logger

    # Workers defaults to 1
    assert c.workers == 1
    c.set("workers", 3)
    assert c.workers == 3

    # Address is parsed
    assert c.address == [("127.0.0.1", 8000)]

    # User and group defaults
    assert os.geteuid() == c.uid
    assert os.getegid() == c.gid

    # Proc name
    assert "gunicorn" == c.proc_name

    # Not a config property
    pytest.raises(AttributeError, getattr, c, "foo")
    # Force to be not an error
    class Baz(object):
        def get(self):
            return 3.14
    c.settings["foo"] = Baz()
    assert c.foo == 3.14

    # Attempt to set a cfg not via c.set
    pytest.raises(AttributeError, setattr, c, "proc_name", "baz")

    # No setting for name
    pytest.raises(AttributeError, c.set, "baz", "bar")


def test_bool_validation():
    c = config.Config()
    assert c.preload_app is False
    c.set("preload_app", True)
    assert c.preload_app is True
    c.set("preload_app", "true")
    assert c.preload_app is True
    c.set("preload_app", "false")
    assert c.preload_app is False
    pytest.raises(ValueError, c.set, "preload_app", "zilch")
    pytest.raises(TypeError, c.set, "preload_app", 4)


def test_pos_int_validation():
    c = config.Config()
    assert c.workers == 1
    c.set("workers", 4)
    assert c.workers == 4
    c.set("workers", "5")
    assert c.workers == 5
    c.set("workers", "0xFF")
    assert c.workers == 255
    c.set("workers", True)
    assert c.workers == 1  # Yes. That's right...
    pytest.raises(ValueError, c.set, "workers", -21)
    pytest.raises(TypeError, c.set, "workers", c)


def test_str_validation():
    c = config.Config()
    assert c.proc_name == "gunicorn"
    c.set("proc_name", " foo ")
    assert c.proc_name == "foo"
    pytest.raises(TypeError, c.set, "proc_name", 2)


def test_str_to_list_validation():
    c = config.Config()
    assert c.forwarded_allow_ips == ["127.0.0.1"]
    c.set("forwarded_allow_ips", "127.0.0.1,192.168.0.1")
    assert c.forwarded_allow_ips == ["127.0.0.1", "192.168.0.1"]
    c.set("forwarded_allow_ips", "")
    assert c.forwarded_allow_ips == []
    c.set("forwarded_allow_ips", None)
    assert c.forwarded_allow_ips == []
    pytest.raises(TypeError, c.set, "forwarded_allow_ips", 1)


def test_callable_validation():
    c = config.Config()
    def func(a, b):
        pass
    c.set("pre_fork", func)
    assert c.pre_fork == func
    pytest.raises(TypeError, c.set, "pre_fork", 1)
    pytest.raises(TypeError, c.set, "pre_fork", lambda x: True)


def test_reload_engine_validation():
    c = config.Config()

    assert c.reload_engine == "auto"

    c.set('reload_engine', 'poll')
    assert c.reload_engine == 'poll'

    pytest.raises(ConfigError, c.set, "reload_engine", "invalid")


def test_callable_validation_for_string():
    from os.path import isdir as testfunc
    assert config.validate_callable(-1)("os.path.isdir") == testfunc

    # invalid values tests
    pytest.raises(
        TypeError,
        config.validate_callable(-1), ""
    )
    pytest.raises(
        TypeError,
        config.validate_callable(-1), "os.path.not_found_func"
    )
    pytest.raises(
        TypeError,
        config.validate_callable(-1), "notfoundmodule.func"
    )


def test_cmd_line():
    with AltArgs(["prog_name", "-b", "blargh"]):
        app = NoConfigApp()
        assert app.cfg.bind == ["blargh"]
    with AltArgs(["prog_name", "-w", "3"]):
        app = NoConfigApp()
        assert app.cfg.workers == 3
    with AltArgs(["prog_name", "--preload"]):
        app = NoConfigApp()
        assert app.cfg.preload_app


def test_cmd_line_invalid_setting(capsys):
    with AltArgs(["prog_name", "-q", "bar"]):
        with pytest.raises(SystemExit):
            NoConfigApp()
        _, err = capsys.readouterr()
        assert  "error: unrecognized arguments: -q" in err


def test_app_config():
    with AltArgs():
        app = NoConfigApp()
    for s in config.KNOWN_SETTINGS:
        assert app.cfg.settings[s.name].validator(s.default) == app.cfg.settings[s.name].get()


def test_load_config():
    with AltArgs(["prog_name", "-c", cfg_file()]):
        app = NoConfigApp()
    assert app.cfg.bind == ["unix:/tmp/bar/baz"]
    assert app.cfg.workers == 3
    assert app.cfg.proc_name == "fooey"


def test_load_config_explicit_file():
    with AltArgs(["prog_name", "-c", "file:%s" % cfg_file()]):
        app = NoConfigApp()
    assert app.cfg.bind == ["unix:/tmp/bar/baz"]
    assert app.cfg.workers == 3
    assert app.cfg.proc_name == "fooey"


def test_load_config_module():
    with AltArgs(["prog_name", "-c", "python:%s" % cfg_module()]):
        app = NoConfigApp()
    assert app.cfg.bind == ["unix:/tmp/bar/baz"]
    assert app.cfg.workers == 3
    assert app.cfg.proc_name == "fooey"


def test_cli_overrides_config():
    with AltArgs(["prog_name", "-c", cfg_file(), "-b", "blarney"]):
        app = NoConfigApp()
    assert app.cfg.bind == ["blarney"]
    assert app.cfg.proc_name == "fooey"


def test_cli_overrides_config_module():
    with AltArgs(["prog_name", "-c", "python:%s" % cfg_module(), "-b", "blarney"]):
        app = NoConfigApp()
    assert app.cfg.bind == ["blarney"]
    assert app.cfg.proc_name == "fooey"


@pytest.fixture
def create_config_file(request):
    default_config = os.path.join(os.path.abspath(os.getcwd()),
                                                      'gunicorn.conf.py')
    with open(default_config, 'w+') as default:
        default.write("bind='0.0.0.0:9090'")

    def fin():
        os.unlink(default_config)
    request.addfinalizer(fin)

    return default


def test_default_config_file(create_config_file):
    assert config.get_default_config_file() == create_config_file.name

    with AltArgs(["prog_name"]):
        app = NoConfigApp()
    assert app.cfg.bind == ["0.0.0.0:9090"]


def test_post_request():
    c = config.Config()

    def post_request_4(worker, req, environ, resp):
        return 4

    def post_request_3(worker, req, environ):
        return 3

    def post_request_2(worker, req):
        return 2

    c.set("post_request", post_request_4)
    assert c.post_request(1, 2, 3, 4) == 4

    c.set("post_request", post_request_3)
    assert c.post_request(1, 2, 3, 4) == 3

    c.set("post_request", post_request_2)
    assert c.post_request(1, 2, 3, 4) == 2


def test_nworkers_changed():
    c = config.Config()

    def nworkers_changed_3(server, new_value, old_value):
        return 3

    c.set("nworkers_changed", nworkers_changed_3)
    assert c.nworkers_changed(1, 2, 3) == 3


def test_statsd_changes_logger():
    c = config.Config()
    assert c.logger_class == glogging.Logger
    c.set('statsd_host', 'localhost:12345')
    assert c.logger_class == statsd.Statsd


class MyLogger(glogging.Logger):
    # dummy custom logger class for testing
    pass


def test_always_use_configured_logger():
    c = config.Config()
    c.set('logger_class', __name__ + '.MyLogger')
    assert c.logger_class == MyLogger
    c.set('statsd_host', 'localhost:12345')
    # still uses custom logger over statsd
    assert c.logger_class == MyLogger


def test_load_enviroment_variables_config(monkeypatch):
    monkeypatch.setenv("GUNICORN_CMD_ARGS", "--workers=4")
    with AltArgs():
        app = NoConfigApp()
    assert app.cfg.workers == 4

def test_config_file_environment_variable(monkeypatch):
    monkeypatch.setenv("GUNICORN_CMD_ARGS", "--config=" + alt_cfg_file())
    with AltArgs():
        app = NoConfigApp()
    assert app.cfg.proc_name == "not-fooey"
    assert app.cfg.config == alt_cfg_file()
    with AltArgs(["prog_name", "--config", cfg_file()]):
        app = NoConfigApp()
    assert app.cfg.proc_name == "fooey"
    assert app.cfg.config == cfg_file()

def test_invalid_enviroment_variables_config(monkeypatch, capsys):
    monkeypatch.setenv("GUNICORN_CMD_ARGS", "--foo=bar")
    with AltArgs():
        with pytest.raises(SystemExit):
            NoConfigApp()
        _, err = capsys.readouterr()
        assert  "error: unrecognized arguments: --foo" in err

def test_cli_overrides_enviroment_variables_module(monkeypatch):
    monkeypatch.setenv("GUNICORN_CMD_ARGS", "--workers=4")
    with AltArgs(["prog_name", "-c", cfg_file(), "--workers", "3"]):
        app = NoConfigApp()
    assert app.cfg.workers == 3


@pytest.mark.parametrize("options, expected", [
    (["myapp:app"], False),
    (["--reload", "myapp:app"], True),
    (["--reload", "--", "myapp:app"], True),
    (["--reload", "-w 2", "myapp:app"], True),
])
def test_reload(options, expected):
    cmdline = ["prog_name"]
    cmdline.extend(options)
    with AltArgs(cmdline):
        app = NoConfigApp()
    assert app.cfg.reload == expected


@pytest.mark.parametrize("options, expected", [
    (["--umask", "0", "myapp:app"], 0),
    (["--umask", "0o0", "myapp:app"], 0),
    (["--umask", "0x0", "myapp:app"], 0),
    (["--umask", "0xFF", "myapp:app"], 255),
    (["--umask", "0022", "myapp:app"], 18),
])
def test_umask_config(options, expected):
    cmdline = ["prog_name"]
    cmdline.extend(options)
    with AltArgs(cmdline):
        app = NoConfigApp()
    assert app.cfg.umask == expected
