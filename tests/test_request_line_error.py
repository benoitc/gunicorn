import socket
from unittest import mock

import pytest

from gunicorn.http.errors import (InvalidRequestLine, InvalidResponseHeader,
                                  InvalidResponseHeaderName, LimitRequestHeaders,
                                  LimitRequestLine)
from gunicorn.workers.base import Worker


@pytest.mark.parametrize(
    ("error", "status", "reason"),
    [
        (LimitRequestLine(128, 100), 414, "URI Too Long"),
        (LimitRequestHeaders("header too long"), 431, "Request Header Fields Too Large"),
        (InvalidRequestLine("bad request"), 400, "Bad Request"),
    ],
)
def test_worker_error_response_status(error, status, reason):
    worker = Worker.__new__(Worker)
    worker.log = mock.Mock()
    server, client = socket.socketpair()
    try:
        client.settimeout(2)
        worker.handle_error(None, server, ("127.0.0.1", 5000), error)
        response = client.recv(4096)
    finally:
        server.close()
        client.close()

    assert response.startswith(f"HTTP/1.1 {status} {reason}\r\n".encode())



@pytest.mark.parametrize("error", [
    InvalidResponseHeader("'X-Bad'"),
    InvalidResponseHeaderName("'Bad Name'"),
])
def test_app_response_header_error_is_500(error):
    """A header the application tried to send is the application's fault: 500,
    not the 400 a malformed request gets."""
    worker = Worker.__new__(Worker)
    worker.log = mock.Mock()
    server, client = socket.socketpair()
    try:
        client.settimeout(2)
        worker.handle_error(None, server, ("127.0.0.1", 5000), error)
        response = client.recv(4096)
    finally:
        server.close()
        client.close()

    assert response.startswith(b"HTTP/1.1 500 Internal Server Error\r\n")
    worker.log.exception.assert_called_once()
    worker.log.warning.assert_not_called()
