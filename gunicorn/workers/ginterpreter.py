#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""InterpreterPoolExecutor-based worker using Python 3.14+ sub-interpreters."""

import errno
import os
import select
import sys

from . import base


def _check_interpreter_pool_available():
    """Check if InterpreterPoolExecutor is available (Python 3.14+)."""
    try:
        from concurrent.futures import InterpreterPoolExecutor  # noqa: F401  # pylint: disable=unused-import
        return True
    except ImportError:
        return False


_interpreter_state = {
    'wsgi_app': None,
    'cfg_dict': None,
}


def _init_interpreter(cfg_dict, app_uri):
    """Initialize the interpreter with WSGI app and config."""
    from gunicorn.util import import_app

    _interpreter_state['cfg_dict'] = cfg_dict
    _interpreter_state['wsgi_app'] = import_app(app_uri)


def _handle_request_in_interpreter(fd, client_addr, server_addr, family):
    """Handle a single HTTP request in a sub-interpreter."""
    import socket
    import types

    from gunicorn.http.parser import RequestParser
    from gunicorn.http.wsgi import create

    cfg_dict = _interpreter_state['cfg_dict']
    wsgi_app = _interpreter_state['wsgi_app']

    if cfg_dict is None or wsgi_app is None:
        os.close(fd)
        return

    sock = socket.socket(family, socket.SOCK_STREAM, fileno=fd)
    try:
        sock.settimeout(cfg_dict.get('timeout', 30))

        cfg = types.SimpleNamespace(**cfg_dict)  # pylint: disable=not-a-mapping
        cfg.forwarded_allow_networks = lambda: []
        cfg.proxy_allow_networks = lambda: []

        parser = RequestParser(cfg, sock, client_addr)
        try:
            req = next(parser)
        except StopIteration:
            return

        if not req:
            return

        resp, environ = create(req, sock, client_addr, server_addr, cfg)
        environ['wsgi.multithread'] = True
        environ['wsgi.multiprocess'] = True

        respiter = wsgi_app(environ, resp.start_response)
        try:
            for item in respiter:
                resp.write(item)
            resp.close()
        finally:
            if hasattr(respiter, 'close'):
                respiter.close()

    except socket.timeout:
        pass
    except OSError as e:
        if e.errno not in (errno.EPIPE, errno.ECONNRESET, errno.ENOTCONN):
            raise
    finally:
        try:
            sock.close()
        except Exception:
            pass


class InterpreterWorker(base.Worker):
    """Worker using InterpreterPoolExecutor for true parallelism."""

    def init_process(self):
        if not _check_interpreter_pool_available():
            raise RuntimeError(
                "InterpreterPoolExecutor requires Python 3.14+. "
                f"Current version: {sys.version_info.major}.{sys.version_info.minor}"
            )

        from concurrent.futures import InterpreterPoolExecutor  # pylint: disable=no-name-in-module

        self.cfg_dict = self._extract_config()

        self.app_uri = getattr(self.app, 'app_uri', None) or self.app.cfg.wsgi_app
        if not self.app_uri:
            raise RuntimeError(
                "ginterpreter worker requires wsgi_app config to be set. "
                "Use 'gunicorn myapp:app' or set wsgi_app in config."
            )

        self.executor = InterpreterPoolExecutor(
            max_workers=self.cfg.threads,
            initializer=_init_interpreter,
            initargs=(self.cfg_dict, self.app_uri),
        )

        super().init_process()

    def _extract_config(self):
        cfg = self.cfg
        return {
            'limit_request_line': cfg.limit_request_line,
            'limit_request_fields': cfg.limit_request_fields,
            'limit_request_field_size': cfg.limit_request_field_size,
            'strip_header_spaces': cfg.strip_header_spaces,
            'permit_obsolete_folding': cfg.permit_obsolete_folding,
            'header_map': cfg.header_map,
            'casefold_http_method': cfg.casefold_http_method,
            'permit_unconventional_http_method': cfg.permit_unconventional_http_method,
            'permit_unconventional_http_version': cfg.permit_unconventional_http_version,
            'forwarded_allow_ips': list(cfg.forwarded_allow_ips),
            'forwarder_headers': list(cfg.forwarder_headers),
            'secure_scheme_headers': dict(cfg.secure_scheme_headers),
            'proxy_protocol': cfg.proxy_protocol,
            'proxy_allow_ips': list(cfg.proxy_allow_ips),
            'is_ssl': cfg.is_ssl,
            'sendfile': cfg.sendfile,
            'workers': cfg.workers,
            'errorlog': cfg.errorlog,
            'timeout': cfg.timeout,
        }

    def accept(self, listener):
        client, addr = listener.accept()
        fd = client.fileno()
        family = client.family
        server = listener.getsockname()
        self.executor.submit(
            _handle_request_in_interpreter,
            fd, addr, server, family,
        )
        client.detach()

    def run(self):
        for listener in self.sockets:
            listener.setblocking(False)

        while self.alive:
            self.notify()

            if self.ppid != os.getppid():
                self.log.info("Parent changed, shutting down: %s", self)
                break

            try:
                ready = select.select(self.sockets, [], [], 1.0)
                for listener in ready[0]:
                    try:
                        self.accept(listener)
                    except OSError as e:
                        if e.errno not in (errno.EAGAIN, errno.ECONNABORTED,
                                           errno.EWOULDBLOCK):
                            raise
            except OSError as e:
                if e.errno != errno.EINTR:
                    raise

        self.executor.shutdown(wait=True)

    def handle_quit(self, sig, frame):
        self.executor.shutdown(wait=False)
        super().handle_quit(sig, frame)
