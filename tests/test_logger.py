#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import datetime
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from gunicorn.config import Config
from gunicorn.glogging import Logger


def test_atoms_defaults():
    response = SimpleNamespace(
        status='200', response_length=1024,
        headers=(('Content-Type', 'application/json'),), sent=1024,
    )
    request = SimpleNamespace(headers=(('Accept', 'application/json'),))
    environ = {
        'REQUEST_METHOD': 'GET', 'RAW_URI': '/my/path?foo=bar',
        'PATH_INFO': '/my/path', 'QUERY_STRING': 'foo=bar',
        'SERVER_PROTOCOL': 'HTTP/1.1',
    }
    logger = Logger(Config())
    atoms = logger.atoms(response, request, environ, datetime.timedelta(seconds=1))
    assert isinstance(atoms, dict)
    assert atoms['r'] == 'GET /my/path?foo=bar HTTP/1.1'
    assert atoms['m'] == 'GET'
    assert atoms['U'] == '/my/path'
    assert atoms['q'] == 'foo=bar'
    assert atoms['H'] == 'HTTP/1.1'
    assert atoms['b'] == '1024'
    assert atoms['B'] == 1024
    assert atoms['{accept}i'] == 'application/json'
    assert atoms['{content-type}o'] == 'application/json'


def test_atoms_zero_bytes():
    response = SimpleNamespace(
        status='200', response_length=0,
        headers=(('Content-Type', 'application/json'),), sent=0,
    )
    request = SimpleNamespace(headers=(('Accept', 'application/json'),))
    environ = {
        'REQUEST_METHOD': 'GET', 'RAW_URI': '/my/path?foo=bar',
        'PATH_INFO': '/my/path', 'QUERY_STRING': 'foo=bar',
        'SERVER_PROTOCOL': 'HTTP/1.1',
    }
    logger = Logger(Config())
    atoms = logger.atoms(response, request, environ, datetime.timedelta(seconds=1))
    assert atoms['b'] == '0'
    assert atoms['B'] == 0


@pytest.mark.parametrize('auth', [
    # auth type is case in-sensitive
    'Basic YnJrMHY6',
    'basic YnJrMHY6',
    'BASIC YnJrMHY6',
])
def test_get_username_from_basic_auth_header(auth):
    request = SimpleNamespace(headers=())
    response = SimpleNamespace(
        status='200', response_length=1024, sent=1024,
        headers=(('Content-Type', 'text/plain'),),
    )
    environ = {
        'REQUEST_METHOD': 'GET', 'RAW_URI': '/my/path?foo=bar',
        'PATH_INFO': '/my/path', 'QUERY_STRING': 'foo=bar',
        'SERVER_PROTOCOL': 'HTTP/1.1',
        'HTTP_AUTHORIZATION': auth,
    }
    logger = Logger(Config())
    atoms = logger.atoms(response, request, environ, datetime.timedelta(seconds=1))
    assert atoms['u'] == 'brk0v'


def test_get_username_handles_malformed_basic_auth_header():
    """Should catch a malformed auth header"""
    request = SimpleNamespace(headers=())
    response = SimpleNamespace(
        status='200', response_length=1024, sent=1024,
        headers=(('Content-Type', 'text/plain'),),
    )
    environ = {
        'REQUEST_METHOD': 'GET', 'RAW_URI': '/my/path?foo=bar',
        'PATH_INFO': '/my/path', 'QUERY_STRING': 'foo=bar',
        'SERVER_PROTOCOL': 'HTTP/1.1',
        'HTTP_AUTHORIZATION': 'Basic ixsTtkKzIpVTncfQjbBcnoRNoDfbnaXG',
    }
    logger = Logger(Config())

    atoms = logger.atoms(response, request, environ, datetime.timedelta(seconds=1))
    assert atoms['u'] == '-'


def test_setup_switches_errorlog_path(tmp_path):
    """HUP reload re-runs setup so --error-logfile follows cfg (#3401)."""
    first = tmp_path / "first.log"
    second = tmp_path / "second.log"

    cfg = Config()
    cfg.set("errorlog", str(first))
    logger = Logger(cfg)
    logger.info("before-reload")

    assert first.exists()
    assert "before-reload" in first.read_text()

    cfg.set("errorlog", str(second))
    logger.setup(cfg)
    logger.reopen_files()
    logger.info("after-reload")

    assert second.exists()
    assert "after-reload" in second.read_text()
    assert "after-reload" not in first.read_text()
    bases = [
        Path(getattr(h, "baseFilename")).resolve()
        for h in logger.error_log.handlers
        if getattr(h, "_gunicorn", False) and getattr(h, "baseFilename", None)
    ]
    assert second.resolve() in bases


def test_reopen_files_does_not_reseed_custom_handlers(tmp_path):
    """USR1/reopen must not re-add default gunicorn handlers over custom ones."""
    path = tmp_path / "custom.log"
    cfg = Config()
    cfg.set("errorlog", "-")
    logger = Logger(cfg)
    # Simulate logconfig replacing gunicorn defaults with a custom FileHandler.
    for h in list(logger.error_log.handlers):
        logger.error_log.handlers.remove(h)
        try:
            h.close()
        except Exception:
            pass
    custom = logging.FileHandler(str(path))
    custom.setFormatter(logging.Formatter("%(message)s"))
    logger.error_log.addHandler(custom)
    logger.error_log.setLevel(logging.INFO)
    n_before = len(logger.error_log.handlers)
    logger.reopen_files()
    n_after = len(logger.error_log.handlers)
    assert n_after == n_before
    assert not any(getattr(h, "_gunicorn", False) for h in logger.error_log.handlers)
    logger.info("custom-only")
    assert "custom-only" in path.read_text()


def test_reopen_files_keeps_logging_after_close(tmp_path):
    """USR1/logrotate path must still emit after FileHandler.close()."""
    path = tmp_path / "rotate.log"
    cfg = Config()
    cfg.set("errorlog", str(path))
    logger = Logger(cfg)
    logger.info("pre-rotate")
    logger.reopen_files()
    logger.info("post-rotate")
    body = path.read_text()
    assert "pre-rotate" in body
    assert "post-rotate" in body


def test_reload_rebinds_logger_cfg_and_errorlog(tmp_path, monkeypatch):
    """Arbiter.reload must re-setup logging against reloaded cfg (#3401)."""
    import gunicorn.arbiter as arbiter_mod
    from gunicorn.app.base import BaseApplication

    first = tmp_path / "master-before.log"
    second = tmp_path / "master-after.log"

    class App(BaseApplication):
        def init(self, parser, opts, args):
            return {}

        def load(self):
            return lambda environ, start_response: (
                start_response("200 OK", [("Content-Type", "text/plain")]),
                [b"ok"],
            )[1]

        def load_config(self):
            self.cfg.set("errorlog", str(first))
            self.cfg.set("workers", 1)
            self.cfg.set("bind", "127.0.0.1:0")

        def reload(self):
            # Simulate config file changing errorlog path on HUP.
            self.cfg.set("errorlog", str(second))

    app = App()
    app.load_default_config()
    app.load_config()
    arb = arbiter_mod.Arbiter(app)
    # Avoid real socket/pid/worker side effects.
    monkeypatch.setattr(arb, "spawn_worker", lambda: None)
    monkeypatch.setattr(arb, "manage_workers", lambda: None)
    arb.LISTENERS = []
    arb.pidfile = None
    arb.WORKERS = {}

    arb.log.info("pre-hup")
    assert first.exists()
    assert "pre-hup" in first.read_text()

    arb.reload()
    arb.log.info("post-hup")

    assert second.exists()
    assert "post-hup" in second.read_text()
    assert arb.log.cfg is arb.cfg
    assert arb.cfg.errorlog == str(second)


def test_setup_is_idempotent_with_syslog(tmp_path):
    """Repeated setup/HUP must not stack syslog or file handlers."""
    path = tmp_path / "err.log"
    cfg = Config()
    cfg.set("errorlog", str(path))
    cfg.set("syslog", True)
    # Use /dev/log if present else UDP localhost sink may fail; skip if can't bind.
    logger = Logger(cfg)
    n1 = sum(1 for h in logger.error_log.handlers if getattr(h, "_gunicorn", False))
    logger.setup(cfg)
    logger.setup(cfg)
    n2 = sum(1 for h in logger.error_log.handlers if getattr(h, "_gunicorn", False))
    assert n2 == n1
    types = [type(h).__name__ for h in logger.error_log.handlers if getattr(h, "_gunicorn", False)]
    assert types.count("SysLogHandler") <= 1
    assert types.count("FileHandler") <= 1


def test_accesslog_none_removes_handler(tmp_path):
    path = tmp_path / "access.log"
    cfg = Config()
    cfg.set("accesslog", str(path))
    logger = Logger(cfg)
    assert any(isinstance(h, logging.FileHandler) for h in logger.access_log.handlers)
    cfg.set("accesslog", None)
    logger.setup(cfg)
    assert not any(
        getattr(h, "_gunicorn", False) for h in logger.access_log.handlers
    )


def test_capture_output_setup_closes_previous(tmp_path):
    first = tmp_path / "cap1.log"
    second = tmp_path / "cap2.log"
    cfg = Config()
    cfg.set("errorlog", str(first))
    cfg.set("capture_output", True)
    logger = Logger(cfg)
    first_fd = logger.logfile
    assert first_fd is not None and not first_fd.closed
    cfg.set("errorlog", str(second))
    logger.setup(cfg)
    assert first_fd.closed
    assert logger.logfile is not None and not logger.logfile.closed
    assert Path(logger.logfile.name).resolve() == second.resolve()
