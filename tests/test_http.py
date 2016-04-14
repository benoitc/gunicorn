# -*- encoding: utf-8 -*-

import t
import pytest

from gunicorn import util
from gunicorn.http.body import Body, LengthReader, EOFReader
from gunicorn.http.wsgi import Response
from gunicorn.http.unreader import Unreader, IterUnreader, SocketUnreader
from gunicorn.six import BytesIO
from gunicorn.http.errors import InvalidHeader, InvalidHeaderName

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
    """ tests whether http response headers are USASCII encoded """

    mocked_socket = mock.MagicMock()
    mocked_socket.sendall = mock.MagicMock()

    mocked_request = mock.MagicMock()
    response = Response(mocked_request, mocked_socket, None)

    # set umlaut header
    response.headers.append(('foo', u'häder'))
    with pytest.raises(UnicodeEncodeError):
        response.send_headers()

    # build our own header_str to compare against
    tosend = response.default_headers()
    tosend.extend(["%s: %s\r\n" % (k, v) for k, v in response.headers])
    header_str = "%s\r\n" % "".join(tosend)

    with pytest.raises(UnicodeEncodeError):
        mocked_socket.sendall(util.to_bytestring(header_str,"ascii"))


def test_http_invalid_response_header():
    """ tests whether http response headers are contains control chars """

    mocked_socket = mock.MagicMock()
    mocked_socket.sendall = mock.MagicMock()

    mocked_request = mock.MagicMock()
    response = Response(mocked_request, mocked_socket, None)

    with pytest.raises(InvalidHeader):
        response.start_response("200 OK", [('foo', 'essai\r\n')])

    response = Response(mocked_request, mocked_socket, None)
    with pytest.raises(InvalidHeaderName):
        response.start_response("200 OK", [('foo\r\n', 'essai')])


def test_unreader_read_when_size_is_none():
    unreader = Unreader()
    unreader.chunk = mock.MagicMock(side_effect=[b'qwerty', b'123456', b''])

    assert unreader.read(size=None) == b'qwerty'
    assert unreader.read(size=None) == b'123456'
    assert unreader.read(size=None) == b''


def test_unreader_unread():
    unreader = Unreader()
    unreader.unread(b'hi there')
    assert b'hi there' in unreader.read()


def test_unreader_read_zero_size():
    unreader = Unreader()
    unreader.chunk = mock.MagicMock(side_effect=[b'qwerty', b'asdfgh'])

    assert unreader.read(size=0) == b''


def test_unreader_read_with_nonzero_size():
    unreader = Unreader()
    unreader.chunk = mock.MagicMock(side_effect=[
        b'qwerty', b'asdfgh', b'zxcvbn', b'123456', b'', b''
    ])

    assert unreader.read(size=5) == b'qwert'
    assert unreader.read(size=5) == b'yasdf'
    assert unreader.read(size=5) == b'ghzxc'
    assert unreader.read(size=5) == b'vbn12'
    assert unreader.read(size=5) == b'3456'
    assert unreader.read(size=5) == b''


def test_unreader_raises_excpetion_on_invalid_size():
    unreader = Unreader()
    with pytest.raises(TypeError):
        unreader.read(size='foobar')
    with pytest.raises(TypeError):
        unreader.read(size=3.14)
    with pytest.raises(TypeError):
        unreader.read(size=[])


def test_iter_unreader_chunk():
    iter_unreader = IterUnreader((b'ab', b'cd', b'ef'))

    assert iter_unreader.chunk() == b'ab'
    assert iter_unreader.chunk() == b'cd'
    assert iter_unreader.chunk() == b'ef'
    assert iter_unreader.chunk() == b''
    assert iter_unreader.chunk() == b''


def test_socket_unreader_chunk():
    fake_sock = t.FakeSocket(BytesIO(b'Lorem ipsum dolor'))
    sock_unreader = SocketUnreader(fake_sock, max_chunk=5)

    assert sock_unreader.chunk() == b'Lorem'
    assert sock_unreader.chunk() == b' ipsu'
    assert sock_unreader.chunk() == b'm dol'
    assert sock_unreader.chunk() == b'or'
    assert sock_unreader.chunk() == b''


def test_length_reader_read():
    unreader = IterUnreader((b'Lorem', b'ipsum', b'dolor', b'sit', b'amet'))
    reader = LengthReader(unreader, 13)
    assert reader.read(0) == b''
    assert reader.read(5) == b'Lorem'
    assert reader.read(6) == b'ipsumd'
    assert reader.read(4) == b'ol'
    assert reader.read(100) == b''

    reader = LengthReader(unreader, 10)
    assert reader.read(0) == b''
    assert reader.read(5) == b'orsit'
    assert reader.read(5) == b'amet'
    assert reader.read(100) == b''


def test_length_reader_read_invalid_size():
    reader = LengthReader(None, 5)
    with pytest.raises(TypeError):
        reader.read('100')
    with pytest.raises(TypeError):
        reader.read([100])
    with pytest.raises(ValueError):
        reader.read(-100)


def test_eof_reader_read():
    unreader = IterUnreader((b'Lorem', b'ipsum', b'dolor', b'sit', b'amet'))
    reader = EOFReader(unreader)

    assert reader.read(0) == b''
    assert reader.read(5) == b'Lorem'
    assert reader.read(5) == b'ipsum'
    assert reader.read(3) == b'dol'
    assert reader.read(3) == b'ors'
    assert reader.read(100) == b'itamet'
    assert reader.read(100) == b''


def test_eof_reader_read_invalid_size():
    reader = EOFReader(None)
    with pytest.raises(TypeError):
        reader.read('100')
    with pytest.raises(TypeError):
        reader.read([100])
    with pytest.raises(ValueError):
        reader.read(-100)
