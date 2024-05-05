import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

# pytest does not like exceptions from threads
#  - so use subprocess.Popen for now
# from threading import Thread, Event


GRACEFUL_TIMEOUT = 2
WORKER_COUNT = 3
SERVER_PORT = 2048 + secrets.randbelow(1024 * 14)
# FIXME: should also test inherited socket
SERVER_BIND = "[::1]:%d" % SERVER_PORT
APP_BASENAME = "testsyntax"
APP_APPNAME = "wsgiapp"

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
        *args,
        temp_path,
        start_valid=True,
        use_config=False,
        public_traceback=True,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        # self.launched = Event()
        self.p = None
        assert isinstance(temp_path, Path)
        self.temp_path = temp_path
        self.py_path = (temp_path / ("%s.py" % APP_BASENAME)).absolute()
        self.conf_path = (
            (temp_path / "gunicorn.conf.py").absolute() if use_config else os.devnull
        )
        self._start_valid = start_valid
        self._public_traceback = public_traceback

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
        (self.write_ok if self._start_valid else self.write_bad)()
        self.run()
        return self

    def __exit__(self, *exc):
        if self.p is None:
            return
        self.p.send_signal(signal.SIGKILL)
        stdout, stderr = self.p.communicate(timeout=2)
        ret = self.p.returncode
        assert stdout == b""
        assert ret == 0, (ret, stdout, stderr)

    def run(self):
        self.p = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "gunicorn",
                "--config=%s" % self.conf_path,
                "--log-level=debug",
                "--worker-class=sync",
                "--workers=%d" % WORKER_COUNT,
                "--enable-stdio-inheritance",
                "--access-logfile=-",
                "--disable-redirect-access-to-syslog",
                "--graceful-timeout=%d" % (GRACEFUL_TIMEOUT,),
                "--on-fatal=%s"
                % ("world-readable" if self._public_traceback else "quiet",),
                # "--reload",
                "--reload-extra=%s" % self.py_path,
                "--bind=%s" % SERVER_BIND,
                "--reuse-port",
                "%s:%s" % (APP_BASENAME, APP_APPNAME),
            ],
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

    def _graceful_quit(self):
        self.p.send_signal(signal.SIGTERM)
        # self.p.kill()
        stdout, stderr = self.p.communicate(timeout=2 * GRACEFUL_TIMEOUT)
        assert stdout == b""
        ret = self.p.poll()
        assert ret == 0, (ret, stdout, stderr)
        return stderr.decode("utf-8", "surrogateescape")

    def _read_stdio(self, *, key, timeout_sec, wait_for_keyword):
        # try:
        #    stdout, stderr = self.p.communicate(timeout=timeout)
        # except subprocess.TimeoutExpired:
        buf = ["", ""]
        extra = 0
        for _ in range(timeout_sec * 10):
            for fd, file in enumerate([self.p.stdout, self.p.stderr]):
                read = file.read(64 * 1024)
                if read is not None:
                    buf[fd] += read.decode("utf-8", "surrogateescape")
            if extra or wait_for_keyword in buf[key]:
                extra += 1
            # wait a bit *after* seeing the keyword to increase chance of reading context
            if extra > 3:
                break
            time.sleep(0.1)
        # assert buf[abs(key - 1)] == ""
        assert wait_for_keyword in buf[key], buf[key]
        return buf[key]


class Client:
    def run(self):
        import http.client

        conn = http.client.HTTPConnection(SERVER_BIND, timeout=2)
        conn.request("GET", "/", headers={"Host": "localhost"}, body="GETBODY!")
        return conn.getresponse()


def test_process_request_after_fixing_syntax_error():
    # 1. start up the server with invalid app
    # 2. fixup the app by writing to file
    # 3. await reload: the app should begin working soon

    client = Client()

    with TemporaryDirectory(suffix="_temp_py") as tempdir_name:
        with Server(
            temp_path=Path(tempdir_name), start_valid=False, public_traceback=False
        ) as server:
            OUT = 0
            ERR = 1

            boot_log = server._read_stdio(
                key=ERR, wait_for_keyword="Arbiter booted", timeout_sec=5
            )

            # raise RuntimeError(boot_log)

            assert "SyntaxError: invalid syntax" in boot_log, boot_log
            assert '%s.py", line ' % (APP_BASENAME,) in boot_log

            # worker could not load, request will fail
            response = client.run()
            assert response.status == 500
            assert response.reason == "Internal Server Error"
            body = response.read(64 * 1024).decode("utf-8", "surrogateescape")
            # --on-fatal=quiet responds, but does NOT share traceback
            assert "error" in body.lower()
            assert "load_wsgi" not in body.lower()

            _access_log = server._read_stdio(
                key=OUT,
                wait_for_keyword='GET / HTTP/1.1" 500 ',
                timeout_sec=5,
            )
            # trigger reloader
            server.write_ok()
            # os.utime(editable_file)

            reload_log = server._read_stdio(
                key=ERR, wait_for_keyword="reloading", timeout_sec=5
            )
            assert "%s.py modified" % (APP_BASENAME,) in reload_log
            assert "Booting worker" in reload_log

            # worker did boot now, request should work
            response = client.run()
            assert response.status == 200
            assert response.reason == "OK"
            body = response.read(64 * 1024).decode("utf-8", "surrogateescape")
            assert "response body from app" == body

            _debug_log = server._read_stdio(
                key=ERR,
                wait_for_keyword="stderr from app",
                timeout_sec=5,
            )

            shutdown_log = server._graceful_quit()
            assert "Handling signal: term" in shutdown_log
            assert "Worker exiting " in shutdown_log
            assert "Shutting down: Master" in shutdown_log


def test_process_shutdown_cleanly_after_inserting_syntax_error():
    # 1. start with valid application
    # 2. now insert fatal error by writing to app
    # 3. await reload, the shutdown gracefully

    client = Client()

    with TemporaryDirectory(suffix="_temp_py") as tempdir_name:
        with Server(temp_path=Path(tempdir_name), start_valid=True) as server:
            OUT = 0
            ERR = 1

            boot_log = server._read_stdio(
                key=ERR, wait_for_keyword="Arbiter booted", timeout_sec=5
            )
            assert "Booting worker" in boot_log

            # worker did boot now, request should work
            response = client.run()
            assert response.status == 200
            assert response.reason == "OK"
            body = response.read(64 * 1024).decode("utf-8", "surrogateescape")
            assert "response body from app" == body

            _debug_log = server._read_stdio(
                key=ERR,
                wait_for_keyword="stderr from app",
                timeout_sec=5,
            )

            # trigger reloader
            server.write_bad()
            # os.utime(editable_file)

            # this test can fail flaky, when the keyword is not last line logged
            # .. but the worker count is only logged when changed
            reload_log = server._read_stdio(
                key=ERR,
                wait_for_keyword="SyntaxError: ",
                # wait_for_keyword="%d workers" % WORKER_COUNT,
                timeout_sec=6,
            )
            assert "reloading" in reload_log, reload_log
            assert "%s.py modified" % (APP_BASENAME,) in reload_log
            assert "SyntaxError: invalid syntax" in reload_log, reload_log
            assert '%s.py", line ' % (APP_BASENAME,) in reload_log

            # worker could not load, request will fail
            response = client.run()
            assert response.status == 500
            assert response.reason == "Internal Server Error"
            body = response.read(64 * 1024).decode("utf-8", "surrogateescape")
            # its a traceback
            assert "load_wsgi" in body.lower()

            _access_log = server._read_stdio(
                key=OUT,
                wait_for_keyword='GET / HTTP/1.1" 500 ',
                timeout_sec=5,
            )

            shutdown_log = server._graceful_quit()
            assert "Handling signal: term" in shutdown_log
            assert "Worker exiting " in shutdown_log
            assert "Shutting down: Master" in shutdown_log
