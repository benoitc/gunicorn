# -*- encoding: utf-8 -*-

import t
from gunicorn import util
from gunicorn.http.body import Body
from gunicorn.http.wsgi import Response
from gunicorn.six import BytesIO
try:
    import unittest.mock as mock
except ImportError:
    import mock


def assert_readline(payload, size, expected):
    body = Body(BytesIO(payload))
    assert body.readline(size) == expected


def test_readline_empty_body():
    assert_readline(b"", None, b"")
    assert_readline(b"", 1, b"")


def test_readline_zero_size():
    assert_readline(b"abc", 0, b"")
    assert_readline(b"\n", 0, b"")


def test_readline_new_line_before_size():
    body = Body(BytesIO(b"abc\ndef"))
    assert body.readline(4) == b"abc\n"
    assert body.readline() == b"def"


def test_readline_new_line_after_size():
    body = Body(BytesIO(b"abc\ndef"))
    assert body.readline(2) == b"ab"
    assert body.readline() == b"c\n"


def test_readline_no_new_line():
    body = Body(BytesIO(b"abcdef"))
    assert body.readline() == b"abcdef"
    body = Body(BytesIO(b"abcdef"))
    assert body.readline(2) == b"ab"
    assert body.readline(2) == b"cd"
    assert body.readline(2) == b"ef"


def test_readline_buffer_loaded():
    reader = BytesIO(b"abc\ndef")
    body = Body(reader)
    body.read(1) # load internal buffer
    reader.write(b"g\nhi")
    reader.seek(7)
    assert body.readline() == b"bc\n"
    assert body.readline() == b"defg\n"
    assert body.readline() == b"hi"


def test_readline_buffer_loaded_with_size():
    body = Body(BytesIO(b"abc\ndef"))
    body.read(1)  # load internal buffer
    assert body.readline(2) == b"bc"
    assert body.readline(2) == b"\n"
    assert body.readline(2) == b"de"
    assert body.readline(2) == b"f"


def test_http_header_encoding():
    """ tests whether http response headers are ISO-8859-1 encoded """

    mocked_socket = mock.MagicMock()
    mocked_socket.sendall = mock.MagicMock()
    mocked_request = mock.MagicMock()
    response = Response(mocked_request, mocked_socket, None)

    # set umlaut header
    response.headers.append(('foo', 'häder'))
    response.send_headers()

    # build our own header_str to compare against
    tosend = response.default_headers()
    tosend.extend(["%s: %s\r\n" % (k, v) for k, v in response.headers])
    header_str = "%s\r\n" % "".join(tosend)

    mocked_socket.sendall.assert_called_with(util.to_latin1(header_str))
