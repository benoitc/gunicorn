#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# hint: can see stdout as the (complex) test progresses using:
# python -B -m pytest -s -vvvv --ff \
#   --override-ini=addopts=--strict-markers --exitfirst \
#   -- tests/test_nginx.py

import platform
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from support_subprocess import (
    WORKER_ORDER,
    WORKER_PYTEST_LIST,
    GunicornProcess,
    WrkClient,
    dummy_ssl_cert,
)


# @pytest.mark.parametrize("read_size", [50+secrets.randbelow(2048)])
@WrkClient.pytest_supported()
@pytest.mark.skipif(
    platform.python_implementation() == "PyPy", reason="slow on Github CI"
)
@pytest.mark.parametrize("ssl", [False, True], ids=["plain", "ssl"])
@pytest.mark.parametrize("worker_class", WORKER_PYTEST_LIST)
def test_wrk(*, ssl, worker_class, dummy_ssl_cert, read_size=1024):
    if worker_class == "eventlet" and ssl:
        pytest.skip("eventlet worker does not catch errors in ssl.wrap_socket")

    # avoid ports <= 6178 which may be in use by CI runne
    worker_index = WORKER_ORDER.index(worker_class)
    fixed_port = 6178 + 1024 + (2 if ssl else 0) + (4 * worker_index)
    # FIXME: should also test inherited socket (LISTEN_FDS)
    # FIXME: should also test non-inherited (named) UNIX socket
    gunicorn_bind = "[::1]:%d" % fixed_port

    proxy_method = "https" if ssl else "http"

    with TemporaryDirectory(suffix="_temp_py") as tempdir_name:
        temp_path = Path(tempdir_name)

        with GunicornProcess(
            server_bind=gunicorn_bind,
            worker_class=worker_class,
            read_size=read_size,
            ssl_files=dummy_ssl_cert if ssl else None,
            temp_path=temp_path,
            log_level="info",
        ) as server:
            server.read_stdio(
                stderr=True,
                wait_for_keyword="[INFO] Starting gunicorn",
                timeout_sec=6,
                expect={
                    "[INFO] Booting worker",
                },
            )

            path = "/pytest/basic"
            with WrkClient(proxy_method + "://" + gunicorn_bind, path=path) as client:
                out = client.get()
            # print("##############\n" + out)

            extract = WrkClient.RE_RATE.search(out)
            assert extract is not None, out
            rate = float(extract.groups()[0])
            expected = 50
            if worker_class == "sync":
                expected = 5
            # test way too short to make slow GitHub runners fast on PyPy
            if platform.python_implementation() == "PyPy":
                expected //= 5
            assert rate > expected, (rate, expected)

            server.read_stdio(timeout_sec=2, wait_for_keyword="GET %s HTTP/1.1" % path)
            if ssl:
                pass
                # server.read_stdio(
                #    stderr=True,
                #    wait_for_keyword="[DEBUG] ssl connection closed",
                #    timeout_sec=4,
                # )

            server.graceful_quit(
                ignore={
                    "GET %s HTTP/1.1" % path,
                    "Ignoring connection epipe",
                    "Ignoring connection reset",
                },
                expect={
                    "[INFO] Handling signal: term",
                },
            )
