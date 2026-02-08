#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""InterpreterPoolExecutor-based worker using Python 3.14+ sub-interpreters."""

import errno
import os
import select
import time
import sys

from gunicorn.config import NewSSLContext, PreRequest, PostRequest
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
    'ssl_context': None,
}


def _init_interpreter(cfg_dict, app_uri):
    """Initialize the interpreter with WSGI app and config."""
    import types

    from gunicorn.glogging import Logger
    from gunicorn.util import import_app

    _interpreter_state['cfg_dict'] = cfg_dict
    _interpreter_state['wsgi_app'] = import_app(app_uri)

    if cfg_dict.get('is_ssl'):
        import ssl
        context = ssl.create_default_context(
            ssl.Purpose.CLIENT_AUTH, cafile=cfg_dict.get('ca_certs')
        )
        context.load_cert_chain(
            certfile=cfg_dict['certfile'], keyfile=cfg_dict.get('keyfile')
        )
        context.verify_mode = cfg_dict.get('cert_reqs', ssl.CERT_NONE)
        if cfg_dict.get('ciphers'):
            context.set_ciphers(cfg_dict['ciphers'])
        _interpreter_state['ssl_context'] = context

    cfg_ns = types.SimpleNamespace(**cfg_dict)
    _interpreter_state['log'] = Logger(cfg_ns)


def _handle_request_in_interpreter(fd, client_addr, server_addr, family):
    """Handle a single HTTP request in a sub-interpreter."""
    import socket
    import ssl
    import types
    from datetime import datetime

    from gunicorn.http.parser import RequestParser
    from gunicorn.http.wsgi import create

    cfg_dict = _interpreter_state['cfg_dict']
    wsgi_app = _interpreter_state['wsgi_app']
    log = _interpreter_state['log']

    if cfg_dict is None or wsgi_app is None:
        os.close(fd)
        return

    request_start = datetime.now()
    resp = None
    environ = None

    sock = socket.socket(family, socket.SOCK_STREAM, fileno=fd)
    try:
        ssl_context = _interpreter_state['ssl_context']
        if ssl_context is not None:
            sock = ssl_context.wrap_socket(
                sock,
                server_side=True,
                suppress_ragged_eofs=cfg_dict.get('suppress_ragged_eofs', True),
                do_handshake_on_connect=cfg_dict.get('do_handshake_on_connect', True),
            )
            if not cfg_dict.get('do_handshake_on_connect', True):
                sock.do_handshake()

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
    except ssl.SSLError as e:
        if e.args[0] != ssl.SSL_ERROR_EOF:
            raise
    except OSError as e:
        if e.errno not in (errno.EPIPE, errno.ECONNRESET, errno.ENOTCONN):
            raise
    finally:
        try:
            if resp is not None and environ is not None:
                request_time = datetime.now() - request_start
                log.access(resp, req, environ, request_time)
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass


class InterpreterWorker(base.Worker):
    """Worker using InterpreterPoolExecutor for true parallelism."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.nr_conns = 0
        self.pending_futures = set()

    def init_process(self):
        if not _check_interpreter_pool_available():
            raise RuntimeError(
                "InterpreterPoolExecutor requires Python 3.14+. "
                f"Current version: {sys.version_info.major}.{sys.version_info.minor}"
            )

        from concurrent.futures import InterpreterPoolExecutor  # pylint: disable=no-name-in-module

        if self.cfg.is_ssl and self.cfg.ssl_context is not NewSSLContext.ssl_context:
            raise NotImplementedError(
                "ssl_context hook is not supported with ginterpreter worker "
                "because callables cannot be shared across sub-interpreters."
            )

        if self.cfg.pre_request is not PreRequest.pre_request:
            raise NotImplementedError(
                "pre_request hook is not supported with ginterpreter worker "
                "because callables cannot be shared across sub-interpreters."
            )

        if self.cfg.post_request is not PostRequest.post_request:
            raise NotImplementedError(
                "post_request hook is not supported with ginterpreter worker "
                "because callables cannot be shared across sub-interpreters."
            )

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
            'certfile': cfg.certfile,
            'keyfile': cfg.keyfile,
            'ca_certs': cfg.ca_certs,
            'cert_reqs': cfg.cert_reqs,
            'ciphers': cfg.ciphers,
            'suppress_ragged_eofs': cfg.suppress_ragged_eofs,
            'do_handshake_on_connect': cfg.do_handshake_on_connect,
            'sendfile': cfg.sendfile,
            'workers': cfg.workers,
            'timeout': cfg.timeout,
            # logging
            'accesslog': cfg.accesslog,
            'access_log_format': cfg.access_log_format,
            'errorlog': cfg.errorlog,
            'loglevel': cfg.loglevel,
            'capture_output': False,
            'syslog': cfg.syslog,
            'syslog_addr': cfg.syslog_addr,
            'syslog_prefix': cfg.syslog_prefix,
            'syslog_facility': cfg.syslog_facility,
            'disable_redirect_access_to_syslog': cfg.disable_redirect_access_to_syslog,
            'logconfig': cfg.logconfig,
            'logconfig_dict': cfg.logconfig_dict,
            'logconfig_json': cfg.logconfig_json,
            'user': cfg.user,
            'group': cfg.group,
            'proc_name': cfg.proc_name,
        }

    def accept(self, listener):
        client, addr = listener.accept()
        fd = client.fileno()
        family = client.family
        server = listener.getsockname()
        self.nr_conns += 1
        future = self.executor.submit(
            _handle_request_in_interpreter,
            fd, addr, server, family,
        )
        future.add_done_callback(self._on_request_complete)
        self.pending_futures.add(future)
        client.detach()

    def _on_request_complete(self, future):
        self.pending_futures.discard(future)
        self.nr_conns -= 1
        try:
            future.result()
        except Exception as e:
            self.log.exception("Request failed in sub-interpreter")

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

        for listener in self.sockets:
            listener.close()

        graceful_timeout = time.monotonic() + self.cfg.graceful_timeout
        while self.nr_conns > 0:
            self.notify()
            time_remaining = graceful_timeout - time.monotonic()
            if time_remaining <= 0:
                break
            time.sleep(min(time_remaining, 1.0))

        self.executor.shutdown(wait=False)

    def handle_quit(self, sig, frame):
        self.executor.shutdown(wait=False)
        super().handle_quit(sig, frame)
