#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# hint: can see stdout as the (complex) test progresses using:
# python -B -m pytest -s -vvvv --ff \
#   --override-ini=addopts=--strict-markers --exitfirst \
#   -- tests/test_nginx.py

import importlib
import os
import secrets
import shutil
import signal
import subprocess
import sys
import re
import time
from itertools import chain
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import http.client
    from typing import Any, NamedTuple, Self

# path may be /usr/local/bin for packages ported from other OS
CMD_OPENSSL = shutil.which("openssl")
CMD_WRK = shutil.which("wrk")

RATE = re.compile(r"^Requests/sec: *([0-9]+(?:\.[0-9]+)?)$", re.MULTILINE)

pytestmark = pytest.mark.skipif(
    CMD_OPENSSL is None or CMD_WRK is None,
    reason="need openssl and wrk binaries",
)

STDOUT = 0
STDERR = 1

TEST_SIMPLE = [
    pytest.param("sync"),
    "eventlet",
    "gevent",
    "gevent_wsgi",
    "gevent_pywsgi",
    # "tornado",
    "gthread",
    # "aiohttp.GunicornWebWorker",  # different app signature
    # "aiohttp.GunicornUVLoopWebWorker",  # "
]  # type: list[str|NamedTuple]

WORKER_DEPENDS = {
    "aiohttp.GunicornWebWorker": ["aiohttp"],
    "aiohttp.GunicornUVLoopWebWorker": ["aiohttp", "uvloop"],
    "uvicorn.workers.UvicornWorker": ["uvicorn"],  # deprecated
    "uvicorn.workers.UvicornH11Worker": ["uvicorn"],  # deprecated
    "uvicorn_worker.UvicornWorker": ["uvicorn_worker"],
    "uvicorn_worker.UvicornH11Worker": ["uvicorn_worker"],
    "eventlet": ["eventlet"],
    "gevent": ["gevent"],
    "gevent_wsgi": ["gevent"],
    "gevent_pywsgi": ["gevent"],
    "tornado": ["tornado"],
}
DEP_WANTED = set(chain(*WORKER_DEPENDS.values()))  # type: set[str]
DEP_INSTALLED = set()  # type: set[str]

for dependency in DEP_WANTED:
    try:
        importlib.import_module(dependency)
        DEP_INSTALLED.add(dependency)
    except ImportError:
        pass

for worker_name, worker_needs in WORKER_DEPENDS.items():
    missing = list(pkg for pkg in worker_needs if pkg not in DEP_INSTALLED)
    if missing:
        for T in (TEST_SIMPLE,):
            if worker_name not in T:
                continue
            T.remove(worker_name)
            skipped_worker = pytest.param(
                worker_name, marks=pytest.mark.skip("%s not installed" % (missing[0]))
            )
            T.append(skipped_worker)

WORKER_COUNT = 2
GRACEFUL_TIMEOUT = 10
APP_IMPORT_NAME = "testsyntax"
APP_FUNC_NAME = "myapp"
HTTP_HOST = "local.test"

PY_APPLICATION = f"""
import time
def {APP_FUNC_NAME}(environ, start_response):
    body = b"response body from app"
    response_head = [
        ("Content-Type", "text/plain"),
        ("Content-Length", "%d" % len(body)),
    ]
    start_response("200 OK", response_head)
    time.sleep(0.1)
    return iter([body])
"""

class SubProcess:
    GRACEFUL_SIGNAL = signal.SIGTERM

    def __enter__(self):
        # type: () -> Self
        self.run()
        return self

    def __exit__(self, *exc):
        # type: (*Any) -> None
        if self.p is None:
            return
        self.p.send_signal(signal.SIGKILL)
        stdout, stderr = self.p.communicate(timeout=1 + GRACEFUL_TIMEOUT)
        ret = self.p.returncode
        assert stdout[-512:] == b"", stdout
        assert ret == 0, (ret, stdout, stderr)

    def read_stdio(self, *, key, timeout_sec, wait_for_keyword, expect=None):
        # type: (int, int, str, set[str]|None) -> str
        # try:
        #    stdout, stderr = self.p.communicate(timeout=timeout)
        # except subprocess.TimeoutExpired:
        buf = ["", ""]
        seen_keyword = 0
        unseen_keywords = list(expect or [])
        poll_per_second = 20
        assert key in {0, 1}, key
        assert self.p is not None  # this helps static type checkers
        assert self.p.stdout is not None  # this helps static type checkers
        assert self.p.stderr is not None  # this helps static type checkers
        for _ in range(timeout_sec * poll_per_second):
            keep_reading = False
            for fd, file in enumerate([self.p.stdout, self.p.stderr]):
                read = file.read(64 * 1024)
                if read is not None:
                    buf[fd] += read.decode("utf-8", "surrogateescape")
                    keep_reading = True
            if seen_keyword or wait_for_keyword in buf[key]:
                seen_keyword += 1
            for additional_keyword in tuple(unseen_keywords):
                for somewhere in buf:
                    if additional_keyword in somewhere:
                        unseen_keywords.remove(additional_keyword)
            # gathered all the context we wanted
            if seen_keyword and not unseen_keywords:
                if not keep_reading:
                    break
            # not seen expected output? wait for % of original timeout
            # .. maybe we will still see better error context that way
            if seen_keyword > (0.5 * timeout_sec * poll_per_second):
                break
            # retcode = self.p.poll()
            # if retcode is not None:
            #   break
            time.sleep(1.0 / poll_per_second)
        # assert buf[abs(key - 1)] == ""
        assert wait_for_keyword in buf[key], (wait_for_keyword, *buf)
        assert not unseen_keywords, (unseen_keywords, *buf)
        return buf[key]

    def run(self):
        # type: () -> None
        self.p = subprocess.Popen(
            self._argv,
            bufsize=0,  # allow read to return short
            cwd=self.temp_path,
            shell=False,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        os.set_blocking(self.p.stdout.fileno(), False)
        os.set_blocking(self.p.stderr.fileno(), False)
        assert self.p.stdout is not None  # this helps static type checkers

    def graceful_quit(self, expect=None, ignore=None):
        # type: (set[str]|None) -> str
        if self.p is None:
            raise AssertionError("called graceful_quit() when not running")
        self.p.send_signal(self.GRACEFUL_SIGNAL)
        # self.p.kill()
        stdout = self.p.stdout.read(64 * 1024) or b""
        stderr = self.p.stderr.read(64 * 1024) or b""
        try:
            o, e = self.p.communicate(timeout=GRACEFUL_TIMEOUT)
            stdout += o
            stderr += e
        except subprocess.TimeoutExpired:
            pass
        out = stdout.decode("utf-8", "surrogateescape")
        for line in out.split("\n"):
            if any(i in line for i in (ignore or ())):
                continue
            assert line == ""
        exitcode = self.p.poll()  # will return None if running
        self.p.stdout.close()
        self.p.stderr.close()
        assert exitcode == 0, (exitcode, stdout, stderr)
        # print("output after signal: ", stdout, stderr, exitcode)
        self.p = None
        ret = stderr.decode("utf-8", "surrogateescape")
        for keyword in expect or ():
            assert keyword in ret, (keyword, ret)
        return ret


def generate_dummy_ssl_cert(cert_path, key_path):
    # dummy self-signed cert
    subprocess.check_output(
        [
            CMD_OPENSSL,
            "req",
            "-new",
            "-newkey",
            # "ed25519",
            #  OpenBSD 7.5 / LibreSSL 3.9.0 / Python 3.10.13
            #  ssl.SSLError: [SSL: UNKNOWN_CERTIFICATE_TYPE] unknown certificate type (_ssl.c:3900)
            # workaround: use RSA keys for testing
            "rsa",
            "-outform",
            "PEM",
            "-subj",
            "/C=DE",
            "-addext",
            "subjectAltName=DNS:%s" % (HTTP_HOST),
            "-days",
            "1",
            "-nodes",
            "-x509",
            "-keyout",
            "%s" % (key_path),
            "-out",
            "%s" % (cert_path),
        ],
        shell=False,
    )


@pytest.fixture(scope="session")
def dummy_ssl_cert(tmp_path_factory):
    base_tmp_dir = tmp_path_factory.getbasetemp().parent
    crt = base_tmp_dir / "dummy.crt"
    key = base_tmp_dir / "dummy.key"
    print(crt, key)
    # generate once, reuse for all tests
    # with FileLock("%s.lock" % crt):
    if not crt.is_file():
        generate_dummy_ssl_cert(crt, key)
    return crt, key


class GunicornProcess(SubProcess):
    def __init__(
        self,
        *,
        temp_path,
        server_bind,
        read_size=1024,
        ssl_files=None,
        worker_class="sync",
    ):
        self.conf_path = Path(os.devnull)
        self.p = None  # type: subprocess.Popen[bytes] | None
        assert isinstance(temp_path, Path)
        self.temp_path = temp_path
        self.py_path = (temp_path / ("%s.py" % APP_IMPORT_NAME)).absolute()
        with open(self.py_path, "w+") as f:
            f.write(PY_APPLICATION)

        ssl_opt = []
        if ssl_files is not None:
            cert_path, key_path = ssl_files
            ssl_opt = [
                "--do-handshake-on-connect",
                "--certfile=%s" % cert_path,
                "--keyfile=%s" % key_path,
            ]
        thread_opt = []
        if worker_class != "sync":
            thread_opt = ["--threads=50"]

        self._argv = [
            sys.executable,
            "-m",
            "gunicorn",
            "--config=%s" % self.conf_path,
            "--log-level=info",
            "--worker-class=%s" % worker_class,
            "--workers=%d" % WORKER_COUNT,
            # unsupported at the time this test was submitted
            # "--buf-read-size=%d" % read_size,
            "--enable-stdio-inheritance",
            "--access-logfile=-",
            "--disable-redirect-access-to-syslog",
            "--graceful-timeout=%d" % (GRACEFUL_TIMEOUT,),
            "--bind=%s" % server_bind,
            "--reuse-port",
            *thread_opt,
            *ssl_opt,
            "--",
            f"{APP_IMPORT_NAME}:{APP_FUNC_NAME}",
        ]


class Client:
    def __init__(self, url_base):
        # type: (str) -> None
        self._url_base = url_base
        self._env = os.environ.copy()
        self._env["LC_ALL"] = "C"

    def __enter__(self):
        # type: () -> Self
        return self

    def __exit__(self, *exc):
        pass

    def get(self, path):
        # type: () -> http.client.HTTPResponse
        assert path.startswith("/")
        threads = 10
        connections = 100
        out = subprocess.check_output([CMD_WRK, "-t", "%d" % threads, "-c","%d" % connections, "-d5s","%s%s" % (self._url_base, path, )], shell=False, env=self._env)

        return out.decode("utf-8", "replace")


# @pytest.mark.parametrize("read_size", [50+secrets.randbelow(2048)])
@pytest.mark.parametrize("ssl", [False, True], ids=["plain", "ssl"])
@pytest.mark.parametrize("worker_class", TEST_SIMPLE)
def test_wrk(*, ssl, worker_class, dummy_ssl_cert, read_size=1024):

    if worker_class == "eventlet" and ssl:
        pytest.skip("eventlet worker does not catch errors in ssl.wrap_socket")

    # avoid ports <= 6144 which may be in use by CI runner
    fixed_port = 1024 * 6 + secrets.randbelow(1024 * 9)
    # FIXME: should also test inherited socket (LISTEN_FDS)
    # FIXME: should also test non-inherited (named) UNIX socket
    gunicorn_bind = "[::1]:%d" % fixed_port

    proxy_method="https" if ssl else "http"

    with TemporaryDirectory(suffix="_temp_py") as tempdir_name, Client(
            proxy_method + "://" + gunicorn_bind
    ) as client:
        temp_path = Path(tempdir_name)

        with GunicornProcess(
            server_bind=gunicorn_bind,
            worker_class=worker_class,
            read_size=read_size,
            ssl_files=dummy_ssl_cert if ssl else None,
            temp_path=temp_path,
        ) as server:
            server.read_stdio(
                key=STDERR,
                wait_for_keyword="[INFO] Starting gunicorn",
                timeout_sec=6,
                expect={
                    "[INFO] Booting worker",
                },
            )

            path = "/pytest/basic"
            out = client.get(path)
            print("##############\n" + out)

            extract = RATE.search(out)
            assert extract is not None, out
            rate = float(extract.groups()[0])
            if worker_class == "sync":
                assert rate > 5
            else:
                assert rate > 50

            server.read_stdio(
                key=STDOUT, timeout_sec=2, wait_for_keyword="GET %s HTTP/1.1" % path
            )
            if ssl:
                pass
                #server.read_stdio(
                #    key=STDERR,
                #    wait_for_keyword="[DEBUG] ssl connection closed",
                #    timeout_sec=4,
                #)

            server.graceful_quit(
                ignore={"GET %s HTTP/1.1" % path, "Ignoring connection epipe", "Ignoring connection reset"},
                expect={
                    "[INFO] Handling signal: term",
                },
            )
