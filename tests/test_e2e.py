import os
import platform
import secrets
import signal
import subprocess
import logging
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

# pytest does not like exceptions from threads
#  - so use subprocess.Popen for now
# from threading import Thread, Event

logger = logging.getLogger(__name__)

GRACEFUL_TIMEOUT = 0
TIMEOUT_SEC_PER_SUBTEST = 3.0

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
    "gthread",
    # pytest.param("expected_failure", marks=pytest.mark.xfail),
]

TEST_TOLERATES_BAD_RELOAD = [
    "sync",
    "eventlet",
    "gevent",
    "gevent_wsgi",
    "gevent_pywsgi",
    "gthread",
    # pytest.param("expected_failure", marks=pytest.mark.xfail),
]


try:
    from tornado import options as installed_check_  # pylint: disable=unused-import

    for T in (TEST_TOLERATES_BAD_BOOT, TEST_TOLERATES_BAD_RELOAD):
        T.append(pytest.param("tornado", marks=pytest.mark.xfail))
except ImportError:
    for T in (TEST_TOLERATES_BAD_BOOT, TEST_TOLERATES_BAD_RELOAD):
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
    print("Application called - continue test!", file=sys.stderr)
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

PY_LOG_CONFIG = """
def post_fork(a_, b_):
    pass  # import syntax_error
def post_worker_init(worker):
    worker.log.debug("Worker booted - continue test!")
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


class Server(subprocess.Popen):
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
        assert isinstance(temp_path, Path)
        self.temp_path = temp_path
        self.py_path = (temp_path / ("%s.py" % APP_BASENAME)).absolute()
        self.conf_path = (
            (temp_path / "gunicorn.conf.py").absolute()
            if use_config
            else Path(os.devnull)
        )
        self._write_initial = self.write_ok if start_valid else self.write_bad
        with open(self.conf_path, "w+") as f:
            f.write(PY_LOG_CONFIG)
        self._argv = [
            sys.executable,
            # "-B",  # PYTHONDONTWRITEBYTECODE - avoid inotify reporting __pycache__
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
            "--on-fatal=%s" % ("world-readable" if public_traceback else "brief",),
            # "--reload",
            "--reload-engine=poll",
            "--reload-extra=%s" % self.py_path,
            "--bind=%s" % server_bind,
            "--reuse-port",
            "%s:%s" % (APP_BASENAME, APP_APPNAME),
        ]
        self.last_timestamp = time.monotonic()
        self._write_initial()
        super().__init__(
            self._argv,
            bufsize=0,  # allow read to return short
            cwd=self.temp_path,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )

        os.set_blocking(self.stdout.fileno(), False)
        os.set_blocking(self.stderr.fileno(), False)
        self.assert_fast()
        # self.launched.set()

    def assert_fast(self, limit=TIMEOUT_SEC_PER_SUBTEST):
        now = time.monotonic()
        elapsed = now - self.last_timestamp
        if elapsed > limit:
            try:
                stdout, stderr = self.communicate(timeout=2 + GRACEFUL_TIMEOUT)
            except subprocess.TimeoutExpired:
                stdout, stderr = b"", b""
            assert False, (elapsed, stdout, stderr)
        assert 0 <= elapsed <= limit, elapsed
        self.last_timestamp = now

    def write_bad(self):
        with open(self.conf_path, "w+") as f:
            f.write(PY_LOG_CONFIG)
        with open(self.temp_path / "syntax_error.py", "w+") as f:
            f.write(PY_BAD_IMPORT)
        with open(self.py_path, "w+") as f:
            f.write(PY_BAD)
        self.assert_fast()

    def write_ok(self):
        with open(self.py_path, "w+") as f:
            f.write(PY_OK)
        self.assert_fast()

    def __exit__(self, *exc):
        if self.returncode is None:
            self.send_signal(signal.SIGKILL)
            try:
                stdout, _ = self.communicate(timeout=1)
                if stdout:
                    logger.debug(
                        "stdout not empty on shutdown, sample: %r", stdout[-512:]
                    )
            except subprocess.TimeoutExpired:
                pass
        # still alive
        if self.returncode is None:
            self.kill()  # no need to wait, Popen.__exit__ does that
        super().__exit__(*exc)

    def fast_shutdown(self, expect=()):
        stdout = self.stdout.read(64 * 1024) or b""
        stderr = self.stderr.read(64 * 1024) or b""
        assert self.stdin is None
        if self.returncode is None:
            self.send_signal(signal.SIGQUIT)
            try:
                o, e = self.communicate(timeout=2 + GRACEFUL_TIMEOUT)
                stdout += o
                stderr += e
            except subprocess.TimeoutExpired:
                pass
        assert stdout == b""
        exitcode = self.poll()  # will return None if running
        assert exitcode == 0, (exitcode, stdout, stderr)
        errors = stderr.decode("utf-8", "surrogateescape")
        for keyword in expect:
            assert keyword in errors, (keyword, errors)
        self.assert_fast()
        return stdout, stderr

    def read_stdio(self, *, timeout_sec=5, wait_for=()):
        # try:
        #    stdout, stderr = self.communicate(timeout=timeout)
        # except subprocess.TimeoutExpired:
        buf = ["", ""]
        wanted_strings = set(wait_for)
        poll_per_second = 100
        for _ in range(timeout_sec * poll_per_second):
            for fd, file in enumerate([self.stdout, self.stderr]):
                read = file.read(64 * 1024)
                if read is not None:
                    buf[fd] += read.decode("utf-8", "surrogateescape")
            for either_buf in buf:
                for wanted_str in tuple(wanted_strings):
                    if wanted_str in either_buf:
                        wanted_strings.remove(wanted_str)
            # gathered all the context we wanted
            if not wanted_strings:
                break
            time.sleep(1.0 / poll_per_second)
        for wanted_str in wanted_strings:
            assert any(wanted_str in either_buf for either_buf in buf), (
                wanted_str,
                *buf,
            )
        self.assert_fast(timeout_sec + TIMEOUT_SEC_PER_SUBTEST)
        return buf


class Client:
    def __init__(self, host_port):
        self._host_port = host_port

    def run(self):
        import http.client

        conn = http.client.HTTPConnection(self._host_port, timeout=2)
        conn.request("GET", "/", headers={"Host": "localhost"}, body="GETBODY!")
        return conn.getresponse()


@pytest.mark.skipif(
    platform.python_implementation() == "PyPy", reason="slow on Github CI"
)
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
            use_config=True,
            public_traceback=False,
        ) as server:
            _boot_log = server.read_stdio(
                wait_for={
                    "Arbiter booted",
                    "SyntaxError: invalid syntax",
                    '%s.py", line ' % (APP_BASENAME,),
                    # yes, --on-fatal=brief still calls post_worker_init hook!
                    "Worker booted - continue test!",  # see gunicorn.conf.py
                },
            )

            # raise RuntimeError(boot_log)

            # worker could not load, request will fail
            response = client.run()
            assert response.status == 500, (response.status, response.reason)
            assert response.reason == "Internal Server Error", response.reason
            body = response.read(64 * 1024).decode("utf-8", "surrogateescape")
            # --on-fatal=brief responds, but does NOT share traceback
            assert "error" in body.lower()
            assert "load_wsgi" not in body.lower()

            _access_log = server.read_stdio(
                wait_for={'"GET / HTTP/1.1" 500 '},
            )

            # trigger reloader
            server.write_ok()
            # os.utime(editable_file)

            _reload_log = server.read_stdio(
                wait_for={
                    "reloading",
                    "%s.py modified" % (APP_BASENAME,),
                    "Booting worker",
                    "Worker exiting",  # safeguard against hitting the old worker
                    "Worker booted - continue test!",  # see gunicorn.conf.py
                },
            )

            # worker did boot now, request should work
            response = client.run()
            assert response.status == 200, (response.status, response.reason)
            assert response.reason == "OK", response.reason
            body = response.read(64 * 1024).decode("utf-8", "surrogateescape")
            assert "response body from app" == body

            server.assert_fast()

            _debug_log = server.read_stdio(
                wait_for={
                    "Application called - continue test!",
                    # read access log
                    '"GET / HTTP/1.1"',
                },
            )

            _shutdown_log = server.fast_shutdown(
                expect={
                    # "Handling signal: term",
                    "Handling signal: quit",
                    # "Worker exiting ",  # need graceful-timouet >= 1 to log
                    "Shutting down: Master",
                }
            )


@pytest.mark.skipif(
    platform.python_implementation() == "PyPy", reason="slow on Github CI"
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
            use_config=True,
            start_valid=True,
        ) as server:
            _boot_log = server.read_stdio(
                wait_for={
                    "Arbiter booted",
                    "Booting worker",
                    "Worker booted - continue test!",  # see gunicorn.conf.py
                },
            )

            # worker did boot now, request should work
            response = client.run()
            assert response.status == 200, (response.status, response.reason)
            assert response.reason == "OK", response.reason
            body = response.read(64 * 1024).decode("utf-8", "surrogateescape")
            assert "response body from app" == body

            server.assert_fast()

            _debug_log = server.read_stdio(
                wait_for={"Application called - continue test!"},
            )

            # trigger reloader
            server.write_bad()
            # os.utime(editable_file)

            # this test can fail flaky, when the keyword is not last line logged
            # .. but the worker count is only logged when changed
            _reload_log = server.read_stdio(
                timeout_sec=7,
                wait_for={
                    # "%d workers" % WORKER_COUNT,
                    "SyntaxError: ",
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

            server.assert_fast()

            _access_log = server.read_stdio(
                wait_for={'"GET / HTTP/1.1" 500 '},
            )

            _shutdown_log = server.fast_shutdown(
                expect={
                    # "Handling signal: term",
                    "Handling signal: quit",
                    # "Worker exiting ",  # need graceful-timouet >= 1 to log
                    "Shutting down: Master",
                },
            )
