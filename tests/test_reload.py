import unittest.mock as mock

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

    try:
        worker.init_process()
        reloader.start.assert_called_with()
        reloader.add_extra_file.assert_called_with('syntax_error_filename')
    finally:
        worker.tmp.close()


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

    try:
        worker.load_wsgi = mock.Mock()
        mock_parent = mock.Mock()
        mock_parent.attach_mock(worker.load_wsgi, 'load_wsgi')
        mock_parent.attach_mock(reloader.start, 'reloader_start')

        worker.init_process()
        mock_parent.assert_has_calls([
            mock.call.load_wsgi(),
            mock.call.reloader_start(),
        ])
    finally:
        worker.tmp.close()
