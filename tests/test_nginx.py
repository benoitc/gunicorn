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
import time
from itertools import chain
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING
from filelock import FileLock

import pytest

if TYPE_CHECKING:
    import http.client
    from typing import Any, NamedTuple, Self

CMD_OPENSSL = Path("/usr/bin/openssl")
CMD_NGINX = Path("/usr/sbin/nginx")

pytestmark = pytest.mark.skipif(
    not CMD_OPENSSL.is_file() or not CMD_NGINX.is_file(),
    reason="need %s and %s" % (CMD_OPENSSL, CMD_NGINX),
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
GRACEFUL_TIMEOUT = 3
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
worker_processes 1;
error_log stderr notice;
events {{
  worker_connections 1024;
}}
worker_shutdown_timeout 1;
http {{
  default_type application/octet-stream;
  access_log /dev/stdout combined;
  upstream upstream_gunicorn {{
    server {gunicorn_upstream} fail_timeout=0;
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
        assert stdout == b"", stdout
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
            print("parsing", buf, "waiting for", wait_for_keyword, unseen_keywords)
            for fd, file in enumerate([self.p.stdout, self.p.stderr]):
                read = file.read(64 * 1024)
                if read is not None:
                    buf[fd] += read.decode("utf-8", "surrogateescape")
            if seen_keyword or wait_for_keyword in buf[key]:
                seen_keyword += 1
            for additional_keyword in tuple(unseen_keywords):
                for somewhere in buf:
                    if additional_keyword in somewhere:
                        unseen_keywords.remove(additional_keyword)
            # gathered all the context we wanted
            if seen_keyword and not unseen_keywords:
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

    def graceful_quit(self, expect=None):
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
        assert stdout == b""
        self.p.stdout.close()
        self.p.stderr.close()
        exitcode = self.p.poll()  # will return None if running
        assert exitcode == 0, (exitcode, stdout, stderr)
        print("output after signal: ", stdout, stderr, exitcode)
        self.p = None
        ret = stderr.decode("utf-8", "surrogateescape")
        for keyword in expect or ():
            assert keyword in ret, (keyword, ret)
        return ret


class NginxProcess(SubProcess):
    GRACEFUL_SIGNAL = signal.SIGQUIT

    def __init__(
        self,
        *,
        temp_path,
        config,
    ):
        assert isinstance(temp_path, Path)
        self.conf_path = (temp_path / ("%s.nginx" % APP_IMPORT_NAME)).absolute()
        self.p = None  # type: subprocess.Popen[bytes] | None
        self.temp_path = temp_path
        with open(self.conf_path, "w+") as f:
            f.write(config)
        self._argv = [
            CMD_NGINX,
            # nginx 1.19.5+ added the -e cmdline flag - may be testing earlier
            # "-e", "stderr",
            "-c",
            "%s" % self.conf_path,
        ]


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
    with FileLock("%s.lock" % crt):
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

        self._argv = [
            sys.executable,
            "-m",
            "gunicorn",
            "--config=%s" % self.conf_path,
            "--log-level=debug",
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
            *ssl_opt,
            "--",
            f"{APP_IMPORT_NAME}:{APP_FUNC_NAME}",
        ]


class Client:
    def __init__(self, host_port):
        # type: (str) -> None
        self._host_port = host_port

    def __enter__(self):
        # type: () -> Self
        import http.client

        self.conn = http.client.HTTPConnection(self._host_port, timeout=2)
        return self

    def __exit__(self, *exc):
        self.conn.close()

    def get(self, path):
        # type: () -> http.client.HTTPResponse
        self.conn.request("GET", path, headers={"Host": HTTP_HOST}, body="GETBODY!")
        return self.conn.getresponse()


# @pytest.mark.parametrize("read_size", [50+secrets.randbelow(2048)])
@pytest.mark.parametrize("ssl", [False, True], ids=["plain", "ssl"])
@pytest.mark.parametrize("worker_class", TEST_SIMPLE)
def test_nginx_proxy(*, ssl, worker_class, dummy_ssl_cert, read_size=1024):
    # avoid ports <= 6144 which may be in use by CI runner
    fixed_port = 1024 * 6 + secrets.randbelow(1024 * 9)
    # FIXME: should also test inherited socket (LISTEN_FDS)
    # FIXME: should also test non-inherited (named) UNIX socket
    gunicorn_bind = "[::1]:%d" % fixed_port

    # syntax matches between nginx conf and http client
    nginx_bind = "[::1]:%d" % (fixed_port + 1)

    static_dir = "/run/gunicorn/nonexist"
    # gunicorn_upstream = "unix:/run/gunicorn/for-nginx.sock"
    # syntax "[ipv6]:port" matches between gunicorn and nginx
    gunicorn_upstream = gunicorn_bind

    with TemporaryDirectory(suffix="_temp_py") as tempdir_name, Client(
        nginx_bind
    ) as client:
        temp_path = Path(tempdir_name)
        nginx_config = NGINX_CONFIG_TEMPLATE.format(
            server_bind=nginx_bind,
            pid_path="%s" % (temp_path / "nginx.pid"),
            gunicorn_upstream=gunicorn_upstream,
            server_name=HTTP_HOST,
            static_dir=static_dir,
            proxy_method="https" if ssl else "http",
        )

        with GunicornProcess(
            server_bind=gunicorn_bind,
            worker_class=worker_class,
            read_size=read_size,
            ssl_files=dummy_ssl_cert if ssl else None,
            temp_path=temp_path,
        ) as server, NginxProcess(
            config=nginx_config,
            temp_path=temp_path,
        ) as proxy:
            proxy.read_stdio(
                key=STDERR,
                timeout_sec=4,
                wait_for_keyword="start worker processes",
            )

            server.read_stdio(
                key=STDERR,
                wait_for_keyword="Arbiter booted",
                timeout_sec=4,
                expect={
                    "Booting worker",
                },
            )

            for num_request in range(5):
                path = "/pytest/%d" % (num_request)
                response = client.get(path)
                assert response.status == 200
                assert response.read() == b"response body from app"

                # using 1.1 to not fail on tornado reporting for 1.0
                # nginx sees our HTTP/1.1 request
                proxy.read_stdio(
                    key=STDOUT, timeout_sec=2, wait_for_keyword="GET %s HTTP/1.1" % path
                )
                # gunicorn sees the HTTP/1.1 request from nginx
                server.read_stdio(
                    key=STDOUT, timeout_sec=2, wait_for_keyword="GET %s HTTP/1.1" % path
                )

            server.graceful_quit(
                expect={
                    "Handling signal: term",
                    "Shutting down: Master",
                },
            )
            proxy.graceful_quit()
