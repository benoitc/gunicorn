import importlib
import logging
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
from itertools import chain
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import http.client
    from typing import Any, NamedTuple, Self


logger = logging.getLogger(__name__)

# note: BSD path may be /usr/local/bin for ported packages
CMD_OPENSSL = shutil.which("openssl")
CMD_WRK = shutil.which("wrk")

STDOUT = 0
STDERR = 1
WORKER_COUNT = 2
# shared between gunicorn and nginx proxy
GRACEFUL_TIMEOUT = 1
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
    time.sleep(0.02)
    return iter([body])
"""

# used in string.format() - duplicate {{ and }}
NGINX_CONFIG_TEMPLATE = """
pid {pid_path};
daemon off;
worker_processes 1;
error_log stderr notice;
events {{
  worker_connections 1024;
}}
worker_shutdown_timeout {graceful_timeout};
http {{
  default_type application/octet-stream;
  access_log /dev/stdout combined;
  upstream upstream_gunicorn {{
    # max_fails=0 prevents nginx from assuming unavailable
    #  .. which is nowadays (reasonably) ignored for single server
    server {gunicorn_upstream} max_fails=0;
  }}

  server {{ listen {server_bind} default_server; return 400; }}
  server {{
    listen {server_bind}; client_max_body_size 4G;
    server_name {server_name};
    root {static_dir};
    location / {{ try_files $uri @proxy_to_app; }}

    location @proxy_to_app {{
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
      proxy_set_header Host $http_host;
      proxy_http_version 1.1;
      proxy_redirect off;
      proxy_pass {proxy_method}://upstream_gunicorn;
    }}
  }}
}}
"""

WORKER_PYTEST_LIST = [
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
    "sync": [],
    "gthread": [],
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
WORKER_ORDER = list(WORKER_DEPENDS.keys())

for dependency in DEP_WANTED:
    try:
        importlib.import_module(dependency)
        DEP_INSTALLED.add(dependency)
    except ImportError:
        pass

for worker_name, worker_needs in WORKER_DEPENDS.items():
    missing = list(pkg for pkg in worker_needs if pkg not in DEP_INSTALLED)
    if missing:
        for T in (WORKER_PYTEST_LIST,):
            if worker_name not in T:
                continue
            T.remove(worker_name)
            skipped_worker = pytest.param(
                worker_name, marks=pytest.mark.skip("%s not installed" % (missing[0]))
            )
            T.append(skipped_worker)


class SubProcess(subprocess.Popen):
    GRACEFUL_SIGNAL = signal.SIGQUIT
    EXIT_SIGNAL = signal.SIGINT

    def __exit__(self, *exc):
        # type: (*Any) -> None
        if self.returncode is None:
            self.send_signal(self.EXIT_SIGNAL)
            try:
                stdout, stderr = self.communicate(timeout=1)
                if stdout:
                    logger.debug(
                        f"stdout not empty on shutdown, sample: {stdout[-512:]!r}"
                    )
                assert stdout[-512:] == b"", stdout
            except subprocess.TimeoutExpired:
                pass
            # only helpful for diagnostics. we are shutting down unexpected
            # assert self.returncode == 0, (ret, stdout, stderr)
            logger.debug(f"exit code {self.returncode}")
        if self.returncode is None:
            self.kill()  # no need to wait, Popen.__exit__ does that
        super().__exit__(*exc)

    def read_stdio(self, *, timeout_sec, wait_for_keyword, expect=None, stderr=False):
        # type: (int, int, str, set[str]|None) -> str
        # try:
        #    stdout, stderr = self.communicate(timeout=timeout)
        # except subprocess.TimeoutExpired:
        key = STDERR if stderr else STDOUT
        buf = ["", ""]
        seen_keyword = 0
        unseen_keywords = list(expect or [])
        poll_per_second = 30
        assert key in {0, 1}, key
        assert self.stdout is not None  # this helps static type checkers
        assert self.stderr is not None  # this helps static type checkers
        for _ in range(timeout_sec * poll_per_second):
            keep_reading = False
            logger.debug(
                f"parsing {buf!r} waiting for {wait_for_keyword!r} + {unseen_keywords!r}"
            )
            for fd, file in enumerate([self.stdout, self.stderr]):
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
            # retcode = self.poll()
            # if retcode is not None:
            #   break
            time.sleep(1.0 / poll_per_second)
        # assert buf[abs(key - 1)] == ""
        assert wait_for_keyword in buf[key], (wait_for_keyword, *buf)
        assert not unseen_keywords, (unseen_keywords, *buf)
        return buf[key]

    def __init__(self):
        # type: () -> None
        super().__init__(
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
        os.set_blocking(self.stdout.fileno(), False)
        os.set_blocking(self.stderr.fileno(), False)
        assert self.stdout is not None  # this helps static type checkers

    def graceful_quit(self, expect=None, ignore=None):
        # type: (set[str]|None) -> str
        stdout = self.stdout.read(64 * 1024) or b""
        stderr = self.stderr.read(64 * 1024) or b""
        if self.returncode is None:
            self.send_signal(self.GRACEFUL_SIGNAL)
            try:
                o, e = self.communicate(timeout=2 + GRACEFUL_TIMEOUT)
                stdout += o
                stderr += e
            except subprocess.TimeoutExpired:
                pass
        out = stdout.decode("utf-8", "surrogateescape")
        for line in out.split("\n"):
            if any(i in line for i in (ignore or ())):
                continue
            assert line == ""
        assert self.stdin is None
        # no need to crash still running here, Popen.__exit__ will close
        # self.stdout.close()
        # self.stderr.close()
        exitcode = self.poll()  # will return None if running
        assert exitcode == 0, (self._argv[0], exitcode, stdout, stderr)
        logger.debug("output after signal: ", stdout, stderr, exitcode)
        ret = stderr.decode("utf-8", "surrogateescape")
        for keyword in expect or ():
            assert keyword in ret, (keyword, ret)
        return ret


class NginxProcess(SubProcess):
    # SIGQUIT = drain, SIGTERM = fast shutdown
    GRACEFUL_SIGNAL = signal.SIGQUIT
    EXIT_SIGNAL = signal.SIGTERM

    # test runner may not be system administrator, with PATH lacking /sbin/
    # .. since we know we do not need root for our tests, disregard that
    __default = "/usr/local/bin:/usr/bin"
    _PATH = os.environ.get("PATH", __default) + ":/usr/sbin:/usr/local/sbin"
    CMD_NGINX = shutil.which("nginx", path=_PATH)

    @classmethod
    def gen_config(cls, *, bind, temp_path, upstream, static_dir, ssl):
        return NGINX_CONFIG_TEMPLATE.format(
            server_bind=bind,
            pid_path="%s" % (temp_path / "nginx.pid"),
            gunicorn_upstream=upstream,
            server_name=HTTP_HOST,
            static_dir=static_dir,
            graceful_timeout=GRACEFUL_TIMEOUT,
            proxy_method="https" if ssl else "http",
        )

    @classmethod
    def pytest_supported(cls):
        return pytest.mark.skipif(
            CMD_OPENSSL is None or cls.CMD_NGINX is None,
            reason="need nginx and openssl binaries",
        )

    def __init__(
        self,
        *,
        temp_path,
        config,
    ):
        assert isinstance(temp_path, Path)
        self.conf_path = (temp_path / ("%s.nginx" % APP_IMPORT_NAME)).absolute()
        self.temp_path = temp_path
        with open(self.conf_path, "w+") as f:
            f.write(config)
        self._argv = [
            self.CMD_NGINX,
            # nginx 1.19.5+ added the -e cmdline flag - may be testing earlier
            # "-e", "stderr",
            "-c",
            "%s" % self.conf_path,
        ]
        super().__init__()


def generate_dummy_ssl_cert(cert_path, key_path):
    # dummy self-signed cert
    subprocess.check_call(
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
        stdin=subprocess.DEVNULL,
        stderr=None,
        stdout=subprocess.DEVNULL,
        shell=False,
        timeout=20,
    )


@pytest.fixture(scope="session")
def dummy_ssl_cert(tmp_path_factory):
    base_tmp_dir = tmp_path_factory.getbasetemp().parent
    crt = base_tmp_dir / "pytest-dummy.crt"
    key = base_tmp_dir / "pytest-dummy.key"
    logger.debug(f"pytest dummy certificate: {crt}, {key}")
    # generate once, reuse for all tests
    # with FileLock("%s.lock" % crt):
    if not crt.is_file():
        generate_dummy_ssl_cert(crt, key)
    return crt, key


class GunicornProcess(SubProcess):
    # QUIT = fast shutdown, TERM = graceful shutdown
    GRACEFUL_SIGNAL = signal.SIGTERM
    EXIT_SIGNAL = signal.SIGQUIT

    def __init__(
        self,
        *,
        temp_path,
        server_bind,
        read_size=1024,
        ssl_files=None,
        worker_class="sync",
        log_level="debug",
    ):
        self.conf_path = Path(os.devnull)
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
            "--log-level=%s" % (log_level,),
            "--worker-class=%s" % (worker_class,),
            "--workers=%d" % WORKER_COUNT,
            # unsupported at the time this test was submitted
            # "--buf-read-size=%d" % read_size,
            "--enable-stdio-inheritance",
            "--access-logfile=-",
            "--disable-redirect-access-to-syslog",
            "--graceful-timeout=%d" % (GRACEFUL_TIMEOUT,),
            "--bind=%s" % server_bind,
            # untested on non-Linux
            # "--reuse-port",
            *thread_opt,
            *ssl_opt,
            "--",
            f"{APP_IMPORT_NAME}:{APP_FUNC_NAME}",
        ]
        super().__init__()


class StdlibClient:
    def __init__(self, host_port):
        # type: (str) -> None
        self._host_port = host_port

    def __enter__(self):
        # type: () -> Self
        import http.client

        self.conn = http.client.HTTPConnection(self._host_port, timeout=5)
        return self

    def __exit__(self, *exc):
        self.conn.close()

    def get(self, path="/", test=False):
        # type: () -> http.client.HTTPResponse
        body = b"GETBODY!"
        self.conn.request(
            "GET",
            path,
            headers={
                "Host": "invalid.invalid." if test else HTTP_HOST,
                "Connection": "close",
                "Content-Length": "%d" % (len(body),),
            },
            body=body,
        )
        return self.conn.getresponse()


class WrkClient(subprocess.Popen):
    RE_RATE = re.compile(r"^Requests/sec: *([0-9]+(?:\.[0-9]+)?)$", re.MULTILINE)

    @classmethod
    def pytest_supported(cls):
        return pytest.mark.skipif(
            CMD_OPENSSL is None or CMD_WRK is None,
            reason="need openssl and wrk binaries",
        )

    def __init__(self, url_base, path):
        # type: (str, str) -> None
        assert path.startswith("/")
        threads = 10
        connections = 100
        self._env = os.environ.copy()
        self._env["LC_ALL"] = "C"
        super().__init__(
            [
                CMD_WRK,
                "-t",
                "%d" % threads,
                "-c",
                "%d" % connections,
                "-d5s",
                "%s%s"
                % (
                    url_base,
                    path,
                ),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=self._env,
        )

    def get(self):
        out = self.stdout.read(1024 * 4)
        ret = self.wait()
        assert ret == 0, ret
        return out.decode("utf-8", "replace")


__all__ = [
    WORKER_PYTEST_LIST,
    WORKER_ORDER,
    NginxProcess,
    GunicornProcess,
    StdlibClient,
    WrkClient,
]
