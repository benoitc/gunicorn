import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

# pytest does not like exceptions from threads
#  - so use subprocess.Popen for now
# from threading import Thread, Event


GRACEFUL_TIMEOUT = 3

# test flaky for WORKER_COUNT != 1, awaiting *last* worker not implemented
WORKER_COUNT = 1
APP_BASENAME = "testsyntax"
APP_APPNAME = "wsgiapp"

TEST_TOLERATES_BAD_BOOT = [
    "sync",
    "eventlet",
    "gevent",
    "gevent_wsgi",
    "gevent_pywsgi",
    "tornado",
    "gthread",
    # pytest.param("expected_failure", marks=pytest.mark.xfail),
]

TEST_TOLERATES_BAD_RELOAD = [
    "sync",
    "eventlet",
    "gevent",
    "gevent_wsgi",
    "gevent_pywsgi",
    "tornado",
    "gthread",
    # pytest.param("expected_failure", marks=pytest.mark.xfail),
]


try:
    from tornado import options
except ImportError:
    for T in (TEST_TOLERATES_BAD_BOOT, TEST_TOLERATES_BAD_RELOAD):
        T.remove("tornado")
        T.append(
            pytest.param("tornado", marks=pytest.mark.skip("tornado not installed"))
        )


PY_OK = """
import sys
import logging

if sys.version_info >= (3, 8):
    logging.basicConfig(force=True)
    logger = logging.getLogger(__name__)
    logger.info("logger has been reset")
else:
    logging.basicConfig()
    logger = logging.getLogger(__name__)

def wsgiapp(environ_, start_response):
    # print("stdout from app", file=sys.stdout)
    print("stderr from app", file=sys.stderr)
    # needed for Python <= 3.8
    sys.stderr.flush()
    body = b"response body from app"
    response_head = [
        ("Content-Type", "text/plain"),
        ("Content-Length", "%d" % len(body)),
    ]
    start_response("200 OK", response_head)
    return iter([body])
"""

PY_BAD_CONFIG = """
def post_fork(a_, b_):
    pass  # import syntax_error
def post_worker_init(_):
    pass  # raise KeyboardInterrupt
"""

PY_BAD_IMPORT = """
def bad_method():
    syntax_error:
"""

PY_BAD = """
import sys
import logging

import signal
import os

if sys.version_info >= (3, 8):
    logging.basicConfig(force=True)
    logger = logging.getLogger(__name__)
    logger.info("logger has been reset")
else:
    logger = logging.getLogger(__name__)
    logging.basicConfig()

# os.kill(os.getppid(), signal.SIGTERM)
# sys.exit(3)
import syntax_error

def wsgiapp(environ_, start_response_):
    raise RuntimeError("The SyntaxError should raise")
"""


class Server:
    def __init__(
        self,
        *,
        temp_path,
        server_bind,
        worker_class,
        start_valid=True,
        use_config=False,
        public_traceback=True,
    ):
        # super().__init__(*args, **kwargs)
        # self.launched = Event()
        self.p = None
        assert isinstance(temp_path, Path)
        self.temp_path = temp_path
        self.py_path = (temp_path / ("%s.py" % APP_BASENAME)).absolute()
        self.conf_path = (
            (temp_path / "gunicorn.conf.py").absolute()
            if use_config
            else Path(os.devnull)
        )
        self._write_initial = self.write_ok if start_valid else self.write_bad
        self._argv = [
            sys.executable,
            "-m",
            "gunicorn",
            "--config=%s" % self.conf_path,
            "--log-level=debug",
            "--worker-class=%s" % worker_class,
            "--workers=%d" % WORKER_COUNT,
            "--enable-stdio-inheritance",
            "--access-logfile=-",
            "--disable-redirect-access-to-syslog",
            "--graceful-timeout=%d" % (GRACEFUL_TIMEOUT,),
            "--on-fatal=%s" % ("world-readable" if public_traceback else "quiet",),
            # "--reload",
            "--reload-extra=%s" % self.py_path,
            "--bind=%s" % server_bind,
            "--reuse-port",
            "%s:%s" % (APP_BASENAME, APP_APPNAME),
        ]

    def write_bad(self):
        with open(self.conf_path, "w+") as f:
            f.write(PY_BAD_CONFIG)
        with open(self.temp_path / "syntax_error.py", "w+") as f:
            f.write(PY_BAD_IMPORT)
        with open(self.py_path, "w+") as f:
            f.write(PY_BAD)

    def write_ok(self):
        with open(self.py_path, "w+") as f:
            f.write(PY_OK)

    def __enter__(self):
        self._write_initial()
        self.run()
        return self

    def __exit__(self, *exc):
        if self.p is None:
            return
        self.p.send_signal(signal.SIGKILL)
        stdout, stderr = self.p.communicate(timeout=2 + GRACEFUL_TIMEOUT)
        ret = self.p.returncode
        assert stdout == b"", stdout
        assert ret == 0, (ret, stdout, stderr)

    def run(self):
        self.p = subprocess.Popen(
            self._argv,
            bufsize=0,  # allow read to return short
            cwd=self.temp_path,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )

        os.set_blocking(self.p.stdout.fileno(), False)
        os.set_blocking(self.p.stderr.fileno(), False)
        # self.launched.set()

    def graceful_quit(self, expect=()):
        self.p.send_signal(signal.SIGTERM)
        # self.p.kill()
        stdout, stderr = self.p.communicate(timeout=2 + GRACEFUL_TIMEOUT)
        assert stdout == b""
        ret = self.p.poll()  # will return None if running
        assert ret == 0, (ret, stdout, stderr)
        self.p = None
        ret = stderr.decode("utf-8", "surrogateescape")
        for keyword in expect:
            assert keyword in ret, (keyword, ret)
        return ret

    def read_stdio(self, *, key, timeout_sec, wait_for_keyword, expect=()):
        # try:
        #    stdout, stderr = self.p.communicate(timeout=timeout)
        # except subprocess.TimeoutExpired:
        buf = ["", ""]
        seen_keyword = 0
        poll_per_second = 20
        for _ in range(timeout_sec * poll_per_second):
            for fd, file in enumerate([self.p.stdout, self.p.stderr]):
                read = file.read(64 * 1024)
                if read is not None:
                    buf[fd] += read.decode("utf-8", "surrogateescape")
            if seen_keyword or wait_for_keyword in buf[key]:
                seen_keyword += 1
            for additional_keyword in tuple(expect):
                for somewhere in buf:
                    if additional_keyword in somewhere:
                        expect.remove(additional_keyword)
            # gathered all the context we wanted
            if seen_keyword and not expect:
                break
            # not seen expected output? wait for % of original timeout
            # .. maybe we will still see better error context that way
            if seen_keyword > (0.50 * timeout_sec * poll_per_second):
                break
            time.sleep(1.0 / poll_per_second)
        # assert buf[abs(key - 1)] == ""
        assert wait_for_keyword in buf[key], (wait_for_keyword, *buf)
        for additional_keyword in expect:
            for somewhere in buf:
                assert additional_keyword in somewhere, (additional_keyword, *buf)
        return buf[key]


class Client:
    def __init__(self, host_port):
        self._host_port = host_port

    def run(self):
        import http.client

        conn = http.client.HTTPConnection(self._host_port, timeout=2)
        conn.request("GET", "/", headers={"Host": "localhost"}, body="GETBODY!")
        return conn.getresponse()


@pytest.mark.parametrize("worker_class", TEST_TOLERATES_BAD_BOOT)
def test_process_request_after_fixing_syntax_error(worker_class):
    # 1. start up the server with invalid app
    # 2. fixup the app by writing to file
    # 3. await reload: the app should begin working soon

    fixed_port = 2048 + secrets.randbelow(1024 * 14)
    # FIXME: should also test inherited socket (LISTEN_FDS)
    server_bind = "[::1]:%d" % fixed_port

    client = Client(server_bind)

    with TemporaryDirectory(suffix="_temp_py") as tempdir_name:
        with Server(
            worker_class=worker_class,
            server_bind=server_bind,
            temp_path=Path(tempdir_name),
            start_valid=False,
            public_traceback=False,
        ) as server:
            OUT = 0
            ERR = 1

            _boot_log = server.read_stdio(
                key=ERR,
                wait_for_keyword="Arbiter booted",
                timeout_sec=5,
                expect={
                    "SyntaxError: invalid syntax",
                    '%s.py", line ' % (APP_BASENAME,),
                },
            )

            # raise RuntimeError(boot_log)

            # worker could not load, request will fail
            response = client.run()
            assert response.status == 500, (response.status, response.reason)
            assert response.reason == "Internal Server Error", response.reason
            body = response.read(64 * 1024).decode("utf-8", "surrogateescape")
            # --on-fatal=quiet responds, but does NOT share traceback
            assert "error" in body.lower()
            assert "load_wsgi" not in body.lower()

            _access_log = server.read_stdio(
                key=OUT,
                wait_for_keyword='"GET / HTTP/1.1" 500 ',
                timeout_sec=5,
            )
            # trigger reloader
            server.write_ok()
            # os.utime(editable_file)

            _reload_log = server.read_stdio(
                key=ERR,
                wait_for_keyword="reloading",
                timeout_sec=5,
                expect={
                    "%s.py modified" % (APP_BASENAME,),
                    "Booting worker",
                },
            )

            # worker did boot now, request should work
            response = client.run()
            assert response.status == 200, (response.status, response.reason)
            assert response.reason == "OK", response.reason
            body = response.read(64 * 1024).decode("utf-8", "surrogateescape")
            assert "response body from app" == body

            _debug_log = server.read_stdio(
                key=ERR,
                wait_for_keyword="stderr from app",
                timeout_sec=5,
                expect={
                    # read access log
                    '"GET / HTTP/1.1"',
                },
            )

            _shutdown_log = server.graceful_quit(
                expect={
                    "Handling signal: term",
                    "Worker exiting ",
                    "Shutting down: Master",
                }
            )


@pytest.mark.parametrize("worker_class", TEST_TOLERATES_BAD_RELOAD)
def test_process_shutdown_cleanly_after_inserting_syntax_error(worker_class):
    # 1. start with valid application
    # 2. now insert fatal error by writing to app
    # 3. await reload, the shutdown gracefully

    fixed_port = 2048 + secrets.randbelow(1024 * 14)
    # FIXME: should also test inherited socket (LISTEN_FDS)
    server_bind = "[::1]:%d" % fixed_port

    client = Client(server_bind)

    with TemporaryDirectory(suffix="_temp_py") as tempdir_name:
        with Server(
            server_bind=server_bind,
            worker_class=worker_class,
            temp_path=Path(tempdir_name),
            start_valid=True,
        ) as server:
            OUT = 0
            ERR = 1

            _boot_log = server.read_stdio(
                key=ERR,
                wait_for_keyword="Arbiter booted",
                timeout_sec=5,
                expect={
                    "Booting worker",
                },
            )

            # worker did boot now, request should work
            response = client.run()
            assert response.status == 200, (response.status, response.reason)
            assert response.reason == "OK", response.reason
            body = response.read(64 * 1024).decode("utf-8", "surrogateescape")
            assert "response body from app" == body

            _debug_log = server.read_stdio(
                key=ERR,
                wait_for_keyword="stderr from app",
                timeout_sec=5,
            )

            # trigger reloader
            server.write_bad()
            # os.utime(editable_file)

            # this test can fail flaky, when the keyword is not last line logged
            # .. but the worker count is only logged when changed
            _reload_log = server.read_stdio(
                key=ERR,
                wait_for_keyword="SyntaxError: ",
                # wait_for_keyword="%d workers" % WORKER_COUNT,
                timeout_sec=6,
                expect={
                    "reloading",
                    "%s.py modified" % (APP_BASENAME,),
                    "SyntaxError: invalid syntax",
                    '%s.py", line ' % (APP_BASENAME,),
                },
            )

            # worker could not load, request will fail
            response = client.run()
            assert response.status == 500, (response.status, response.reason)
            assert response.reason == "Internal Server Error", response.reason
            body = response.read(64 * 1024).decode("utf-8", "surrogateescape")
            # its a traceback
            assert "load_wsgi" in body.lower()

            _access_log = server.read_stdio(
                key=OUT,
                wait_for_keyword='"GET / HTTP/1.1" 500 ',
                timeout_sec=5,
            )

            _shutdown_log = server.graceful_quit(
                expect={
                    "Handling signal: term",
                    "Worker exiting ",
                    "Shutting down: Master",
                },
            )
