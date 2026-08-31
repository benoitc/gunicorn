#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import unittest.mock as mock

import pytest

from gunicorn.app.base import Application
from gunicorn.workers.base import Worker
from gunicorn.reloader import reloader_engines


class ReloadApp(Application):
    def __init__(self):
        super().__init__("no usage", prog="gunicorn_test")

    def do_load_config(self):
        self.load_default_config()
        self.cfg.set('reload', True)
        self.cfg.set('reload_engine', 'poll')


class SyntaxErrorApp(ReloadApp):
    def wsgi(self):
        error = SyntaxError('invalid syntax')
        error.filename = 'syntax_error_filename'
        raise error


class MyWorker(Worker):
    def run(self):
        pass


def test_reload_on_syntax_error():
    """
    Test that reloading works if the application has a syntax error.
    """
    reloader = mock.Mock()
    reloader_engines['poll'] = lambda *args, **kw: reloader

    app = SyntaxErrorApp()
    cfg = app.cfg
    log = mock.Mock()
    worker = MyWorker(age=0, ppid=0, sockets=[], app=app, timeout=0, cfg=cfg, log=log)

    worker.init_process()
    reloader.start.assert_called_with()
    reloader.add_extra_file.assert_called_with('syntax_error_filename')


def test_start_reloader_after_load_wsgi():
    """
    Check that the reloader is started after the wsgi app has been loaded.
    """
    reloader = mock.Mock()
    reloader_engines['poll'] = lambda *args, **kw: reloader

    app = ReloadApp()
    cfg = app.cfg
    log = mock.Mock()
    worker = MyWorker(age=0, ppid=0, sockets=[], app=app, timeout=0, cfg=cfg, log=log)

    worker.load_wsgi = mock.Mock()
    mock_parent = mock.Mock()
    mock_parent.attach_mock(worker.load_wsgi, 'load_wsgi')
    mock_parent.attach_mock(reloader.start, 'reloader_start')

    worker.init_process()
    mock_parent.assert_has_calls([
        mock.call.load_wsgi(),
        mock.call.reloader_start(),
    ])


def test_inotify_extra_file_current_dir():
    """Relative extra files in the cwd should not crash the inotify reloader."""
    pytest.importorskip("inotify", reason="inotify reloader requires the inotify package")

    from gunicorn import reloader as reloader_mod

    if not reloader_mod.has_inotify:
        pytest.skip("inotify reloader is only available on Linux")

    calls = []

    # Build a reloader and force the dirname('') path through add_extra_file.
    r = reloader_mod.InotifyReloader(callback=lambda f: None)

    # Replace watcher with a mock-like object that records add_watch dirs.
    class FakeWatcher:
        def add_watch(self, dirname, mask=None):
            calls.append(dirname)

        def event_gen(self):
            return []

    r._watcher = FakeWatcher()
    r.add_extra_file('.env')
    assert calls == ['.']
    assert '.env' in r._extra_files
    assert '.' in r._dirs


def test_extra_patterns_expand_on_every_call(tmp_path):
    """Files created after startup are picked up without a restart."""
    from gunicorn.reloader import Reloader

    views = tmp_path / "views"
    views.mkdir()
    first = views / "a.json"
    first.write_text("{}")

    r = Reloader(extra_files=[str(views / "*.json")])

    assert r._extra_files == set()
    assert str(first) in r.get_files()

    second = views / "b.json"
    second.write_text("{}")

    assert str(second) in r.get_files()


def test_extra_files_and_patterns_are_separated(tmp_path):
    from gunicorn.reloader import Reloader

    plain = tmp_path / "plain.txt"
    plain.write_text("plain")
    pattern = str(tmp_path / "*.json")

    r = Reloader(extra_files=[str(plain), pattern])

    assert r._extra_files == {str(plain)}
    assert r._extra_patterns == {pattern}


def test_recursive_pattern_matches_nested_files(tmp_path):
    from gunicorn.reloader import Reloader

    nested = tmp_path / "ui" / "deep" / "deeper"
    nested.mkdir(parents=True)
    target = nested / "config.json"
    target.write_text("{}")

    r = Reloader(extra_files=[str(tmp_path / "**" / "config.json")])

    assert str(target) in r.get_files()
