#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import io
import t
import pytest
from unittest import mock

from gunicorn import util
from gunicorn.http.body import Body, ChunkedReader, LengthReader, EOFReader
from gunicorn.http.wsgi import FileWrapper, Response
from gunicorn.http.unreader import Unreader, IterUnreader, SocketUnreader
from gunicorn.http.errors import (InvalidChunkSize, InvalidHeader, InvalidHeaderName,
                                  InvalidHTTPVersion, LimitRequestHeaders)
from gunicorn.http.message import TOKEN_RE


def test_method_pattern():
    assert TOKEN_RE.fullmatch("GET")
    assert TOKEN_RE.fullmatch("MKCALENDAR")
    assert not TOKEN_RE.fullmatch("GET:")
    assert not TOKEN_RE.fullmatch("GET;")
    RFC9110_5_6_2_TOKEN_DELIM = r'"(),/:;<=>?@[\]{}'
    for bad_char in RFC9110_5_6_2_TOKEN_DELIM:
        assert not TOKEN_RE.match(bad_char)


def assert_readline(payload, size, expected):
    body = Body(io.BytesIO(payload))
    assert body.readline(size) == expected


def test_readline_empty_body():
    assert_readline(b"", None, b"")
    assert_readline(b"", 1, b"")


def test_readline_zero_size():
    assert_readline(b"abc", 0, b"")
    assert_readline(b"\n", 0, b"")


def test_readline_new_line_before_size():
    body = Body(io.BytesIO(b"abc\ndef"))
    assert body.readline(4) == b"abc\n"
    assert body.readline() == b"def"


def test_readline_new_line_after_size():
    body = Body(io.BytesIO(b"abc\ndef"))
    assert body.readline(2) == b"ab"
    assert body.readline() == b"c\n"


def test_readline_no_new_line():
    body = Body(io.BytesIO(b"abcdef"))
    assert body.readline() == b"abcdef"
    body = Body(io.BytesIO(b"abcdef"))
    assert body.readline(2) == b"ab"
    assert body.readline(2) == b"cd"
    assert body.readline(2) == b"ef"


def test_readline_buffer_loaded():
    reader = io.BytesIO(b"abc\ndef")
    body = Body(reader)
    body.read(1) # load internal buffer
    reader.write(b"g\nhi")
    reader.seek(7)
    assert body.readline() == b"bc\n"
    assert body.readline() == b"defg\n"
    assert body.readline() == b"hi"


def test_readline_buffer_loaded_with_size():
    body = Body(io.BytesIO(b"abc\ndef"))
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

    # set umlaut header value - latin-1 is OK
    response.headers.append(('foo', 'häder'))
    response.send_headers()

    # set a-breve header value - unicode, non-latin-1 fails
    response = Response(mocked_request, mocked_socket, None)
    response.headers.append(('apple', 'măr'))
    with pytest.raises(UnicodeEncodeError):
        response.send_headers()

    # build our own header_str to compare against
    tosend = response.default_headers()
    tosend.extend(["%s: %s\r\n" % (k, v) for k, v in response.headers])
    header_str = "%s\r\n" % "".join(tosend)

    with pytest.raises(UnicodeEncodeError):
        mocked_socket.sendall(util.to_bytestring(header_str, "ascii"))


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


def test_unreader_unread_should_place_data_at_the_beginning_of_the_buffer():
    unreader = IterUnreader([b"abc", b"def"])
    ab = unreader.read(2)
    unreader.unread(ab)

    assert unreader.read(None) == b"abc"


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
    fake_sock = t.FakeSocket(io.BytesIO(b'Lorem ipsum dolor'))
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


def test_invalid_http_version_error():
    assert str(InvalidHTTPVersion('foo')) == "Invalid HTTP Version: 'foo'"
    assert str(InvalidHTTPVersion((2, 1))) == 'Invalid HTTP Version: (2, 1)'


def _build_request_parser(payload):
    """Construct a RequestParser that drains the given bytes."""
    from gunicorn.config import Config
    from gunicorn.http.parser import RequestParser

    cfg = Config()
    parser = RequestParser(cfg, iter([payload]), None)
    next(iter(parser))
    return parser


def test_finish_body_drains_remainder():
    payload = (
        b"POST / HTTP/1.1\r\n"
        b"Host: example.com\r\n"
        b"Content-Length: 5\r\n"
        b"\r\n"
        b"hello"
    )
    parser = _build_request_parser(payload)
    assert parser.finish_body() is True


def test_finish_body_returns_false_when_byte_cap_exceeded():
    body = b"x" * (4096)
    payload = (
        b"POST / HTTP/1.1\r\n"
        b"Host: example.com\r\n"
        b"Content-Length: %d\r\n\r\n%s" % (len(body), body)
    )
    parser = _build_request_parser(payload)
    assert parser.finish_body(max_bytes=512) is False


def test_finish_body_no_cap_without_deadline():
    """Without a deadline, finish_body MUST drain the full body even when it
    exceeds _DRAIN_MAX_BYTES. The byte cap only applies under a deadline.

    Regression: a 64 KiB cap on every call silently desynced base_async/sync
    workers that iterate the parser via __next__ (which discards the return
    value), leading to the next request being misparsed from residual body
    bytes left on the wire.
    """
    body = b"x" * (128 * 1024)  # well over _DRAIN_MAX_BYTES
    payload = (
        b"POST / HTTP/1.1\r\n"
        b"Host: example.com\r\n"
        b"Content-Length: %d\r\n\r\n%s" % (len(body), body)
    )
    parser = _build_request_parser(payload)
    assert parser.finish_body() is True


def test_finish_body_applies_cap_only_under_deadline():
    """When a deadline is set and max_bytes is left at the default, the
    implicit _DRAIN_MAX_BYTES cap kicks in to defend against a slow client
    trickling under the deadline."""
    from gunicorn.http.parser import _DRAIN_MAX_BYTES

    body = b"x" * (_DRAIN_MAX_BYTES + 1024)
    payload = (
        b"POST / HTTP/1.1\r\n"
        b"Host: example.com\r\n"
        b"Content-Length: %d\r\n\r\n%s" % (len(body), body)
    )
    import time as _time
    far_future = _time.monotonic() + 60.0

    parser = _build_request_parser(payload)
    assert parser.finish_body(deadline=far_future) is False


def test_finish_body_returns_false_on_expired_deadline():
    payload = (
        b"POST / HTTP/1.1\r\n"
        b"Host: example.com\r\n"
        b"Content-Length: 100\r\n"
        b"\r\n"
        b"only-partial"
    )
    import time as _time

    parser = _build_request_parser(payload)
    # Force an already-elapsed deadline; the drain must abandon immediately.
    expired = _time.monotonic() - 1.0
    # IterUnreader has no socket; deadline path is exercised only when sock
    # is present. Stub a sock with gettimeout/settimeout to drive the branch.
    sock = mock.Mock()
    sock.gettimeout.return_value = None
    parser.unreader.sock = sock
    assert parser.finish_body(deadline=expired) is False
    sock.settimeout.assert_called_with(None)


def test_file_wrapper_iterable():
    """FileWrapper should support the iterator protocol per PEP 3333."""
    filelike = io.BytesIO(b"hello world")
    wrapper = FileWrapper(filelike, blksize=5)

    # Should be iterable
    assert hasattr(wrapper, '__iter__')
    assert hasattr(wrapper, '__next__')
    assert iter(wrapper) is wrapper

    # Should yield chunks via next()
    assert next(wrapper) == b"hello"
    assert next(wrapper) == b" worl"
    assert next(wrapper) == b"d"
    with pytest.raises(StopIteration):
        next(wrapper)

    # Also works with for loop
    filelike2 = io.BytesIO(b"abc")
    wrapper2 = FileWrapper(filelike2, blksize=2)
    chunks = list(wrapper2)
    assert chunks == [b"ab", b"c"]


def _make_response(method="GET", version=(1, 1), sendfile=False):
    sock = mock.MagicMock()
    req = mock.MagicMock()
    req.method = method
    req.version = version
    req.should_close.return_value = False
    cfg = mock.MagicMock()
    cfg.is_ssl = False
    cfg.sendfile = sendfile
    return Response(req, sock, cfg), sock


@pytest.mark.parametrize("status,method,expect_cl", [
    ("204 No Content", "GET", False),
    ("100 Continue", "GET", False),
    ("199 Custom", "GET", False),
    ("304 Not Modified", "GET", True),
    ("200 OK", "HEAD", True),
])
def test_no_body_response_strips_framing(status, method, expect_cl):
    """1xx/204 strip Content-Length; HEAD/304 keep app-supplied Content-Length."""
    resp, _ = _make_response(method=method)
    body_len = 12
    resp.start_response(status, [
        ("Content-Type", "text/plain"),
        ("Content-Length", str(body_len)),
    ])
    header_keys = [k.lower() for k, _ in resp.headers]
    if expect_cl:
        assert "content-length" in header_keys
        assert resp.response_length == body_len
    else:
        assert "content-length" not in header_keys
        assert resp.response_length is None
    assert resp.chunked is False
    assert resp._omits_body is True


def test_no_body_response_drops_body_and_warns(caplog):
    resp, _ = _make_response(method="GET")
    resp.start_response("204 No Content", [
        ("Content-Type", "text/plain"),
        ("Content-Length", "5"),
    ])
    with caplog.at_level("WARNING", logger="gunicorn.http.wsgi"):
        resp.write(b"hello")
        resp.write(b"again")
    assert resp.sent == 0
    assert sum(
        1 for r in caplog.records
        if "no-body response" in r.getMessage()
    ) == 1


@pytest.mark.parametrize("status,method,extra_headers", [
    ("200 OK", "HEAD", [("Content-Length", "0")]),
    ("204 No Content", "GET", []),
    ("304 Not Modified", "GET", []),
])
def test_no_body_sendfile_empty_file_does_not_warn(
        caplog, tmp_path, status, method, extra_headers):
    """An empty file wrapper has no body bytes to drop, so no warning."""
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")
    resp, sock = _make_response(method=method, sendfile=True)
    resp.start_response(status, [("Content-Type", "text/plain")] + extra_headers)
    with open(path, "rb") as filelike:
        with caplog.at_level("WARNING", logger="gunicorn.http.wsgi"):
            resp.write_file(FileWrapper(filelike))
    assert resp.sent == 0
    sock.sendfile.assert_not_called()
    assert [
        r for r in caplog.records if "no-body response" in r.getMessage()
    ] == []


def test_no_body_sendfile_non_empty_file_warns_once(caplog, tmp_path):
    """A non-empty file wrapper really loses bytes, so it still warns once."""
    path = tmp_path / "data.txt"
    path.write_bytes(b"hello")
    resp, sock = _make_response(method="HEAD", sendfile=True)
    resp.start_response("200 OK", [
        ("Content-Type", "text/plain"),
        ("Content-Length", "5"),
    ])
    with open(path, "rb") as filelike:
        with caplog.at_level("WARNING", logger="gunicorn.http.wsgi"):
            resp.write_file(FileWrapper(filelike))
            resp.write_file(FileWrapper(filelike))
    assert resp.sent == 0
    sock.sendfile.assert_not_called()
    assert sum(
        1 for r in caplog.records
        if "no-body response" in r.getMessage()
    ) == 1


def test_normal_response_unaffected():
    resp, _ = _make_response(method="GET")
    resp.start_response("200 OK", [
        ("Content-Type", "text/plain"),
        ("Content-Length", "5"),
    ])
    assert resp._omits_body is False
    assert resp.response_length == 5
    resp.write(b"hello")
    assert resp.sent == 5


class _CountingUnreader(IterUnreader):
    """An unreader that hands out fixed-size reads and counts them."""

    def __init__(self, blocks):
        super().__init__(iter(blocks))
        self.reads = 0

    def read(self, size=None):
        self.reads += 1
        return super().read(size)


def _chunked_reader(unreader, field_size=8190, headers=8190 * 32):
    req = mock.Mock()
    req.limit_request_field_size = field_size
    req.max_buffer_headers = headers
    req.parse_headers.return_value = [("X-Sum", "1")]
    return req, ChunkedReader(req, unreader)


def test_chunk_size_line_is_bounded():
    """An endless chunk-size line is refused instead of read for ever."""
    unreader = _CountingUnreader([b"a" * 8192 for _ in range(1024)])   # 8MB, no CRLF
    _, reader = _chunked_reader(unreader)
    with pytest.raises(InvalidChunkSize):
        reader.parse_chunk_size(unreader)
    assert unreader.reads <= 3, "kept reading well past the limit"


def test_trailer_section_is_bounded():
    """An endless trailer section is refused instead of read for ever."""
    unreader = _CountingUnreader([b"x" * 8192 for _ in range(1024)])
    _, reader = _chunked_reader(unreader, headers=8190)
    with pytest.raises(LimitRequestHeaders):
        reader.parse_trailers(unreader, b"")
    assert unreader.reads <= 3, "kept reading well past the limit"


def test_chunked_message_split_across_reads():
    """Terminators straddling two reads are found, and long lines still parse.

    Delivered a byte at a time, so every chunk-size line, chunk terminator
    and the trailer section are split at every possible offset.
    """
    message = (b"1;padding=" + b"x" * 200 + b"\r\n"
               b"a\r\n"
               b"2\r\nbc\r\n"
               b"0\r\n"
               b"X-Sum: 1\r\n\r\n"
               b"leftover")
    unreader = IterUnreader(iter([message[i:i + 1] for i in range(len(message))]))
    req, reader = _chunked_reader(unreader)
    assert Body(reader).read(100) == b"abc"
    assert req.parse_headers.call_args[0][0] == b"X-Sum: 1"
    # Whatever followed the message is left for the next request
    assert b"".join(iter(unreader.read, b"")) == b"leftover"
