#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# hint: can see stdout as the (complex) test progresses using:
# python -B -m pytest -s -vvvv --ff \
#   --override-ini=addopts=--strict-markers --exitfirst \
#   -- tests/test_nginx.py

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

import pytest
from support_subprocess import (
    WORKER_ORDER,
    WORKER_PYTEST_LIST,
    GunicornProcess,
    NginxProcess,
    StdlibClient,
    dummy_ssl_cert,
)

if TYPE_CHECKING:
    import http.client
    from typing import Any, NamedTuple, Self


# @pytest.mark.parametrize("read_size", [50+secrets.randbelow(2048)])
@NginxProcess.pytest_supported()
@pytest.mark.parametrize("ssl", [False, True], ids=["plain", "ssl"])
@pytest.mark.parametrize("worker_class", WORKER_PYTEST_LIST)
def test_nginx_proxy(*, ssl, worker_class, dummy_ssl_cert, read_size=1024):
    # avoid ports <= 6178 which may be in use by CI runner
    # avoid quickly reusing ports as they might not be cleared immediately on BSD
    worker_index = WORKER_ORDER.index(worker_class)
    fixed_port = 6178 + 512 + (4 if ssl else 0) + (8 * worker_index)
    # FIXME: should also test inherited socket (LISTEN_FDS)
    # FIXME: should also test non-inherited (named) UNIX socket
    gunicorn_bind = "[::1]:%d" % fixed_port

    # syntax matches between nginx conf and http client
    nginx_bind = "[::1]:%d" % (fixed_port + 2)

    static_dir = "/run/gunicorn/nonexist"
    # gunicorn_upstream = "unix:/run/gunicorn/for-nginx.sock"
    # syntax "[ipv6]:port" matches between gunicorn and nginx
    gunicorn_upstream = gunicorn_bind

    with TemporaryDirectory(suffix="_temp_py") as tempdir_name, StdlibClient(
        nginx_bind
    ) as client:
        temp_path = Path(tempdir_name)
        nginx_config = NginxProcess.gen_config(
            bind=nginx_bind,
            temp_path=temp_path,
            upstream=gunicorn_upstream,
            static_dir=static_dir,
            ssl=ssl,
        )

        with GunicornProcess(
            server_bind=gunicorn_bind,
            worker_class=worker_class,
            read_size=read_size,
            ssl_files=dummy_ssl_cert if ssl else None,
            temp_path=temp_path,
            log_level="debug",
        ) as server, NginxProcess(
            config=nginx_config,
            temp_path=temp_path,
        ) as proxy:
            proxy.read_stdio(
                stderr=True,
                timeout_sec=8,
                wait_for_keyword="start worker processes",
            )

            server.read_stdio(
                stderr=True,
                wait_for_keyword="Arbiter booted",
                timeout_sec=8,
                expect={
                    "Booting worker",
                },
            )

            path = "/dummy"
            try:
                response = client.get(path, test=True)
            except TimeoutError as exc:
                raise AssertionError(f"failed to query proxy: {exc!r}") from exc
            assert response.status == 400
            test_body = response.read()
            assert b"nginx" in test_body
            proxy.read_stdio(timeout_sec=4, wait_for_keyword="GET %s HTTP/1.1" % path)

            for num_request in range(5):
                path = "/pytest/%d" % (num_request)
                try:
                    response = client.get(path)
                except TimeoutError as exc:
                    raise AssertionError(f"failed to fetch {path!r}: {exc!r}") from exc
                assert response.status == 200
                assert response.read() == b"response body from app"

                # using 1.1 to not fail on tornado reporting for 1.0
                # nginx sees our HTTP/1.1 request
                proxy.read_stdio(
                    timeout_sec=4, wait_for_keyword="GET %s HTTP/1.1" % path
                )
                # gunicorn sees the HTTP/1.1 request from nginx
                server.read_stdio(
                    timeout_sec=4, wait_for_keyword="GET %s HTTP/1.1" % path
                )

            server.graceful_quit(
                expect={
                    "Handling signal: term",
                    "Shutting down: Master",
                },
            )
            proxy.graceful_quit()
