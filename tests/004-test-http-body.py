from StringIO import StringIO

import t
from gunicorn.http.body import Body


def assert_readline(payload, size, expected):
    body = Body(StringIO(payload))
    t.eq(body.readline(size), expected)


def test_readline_empty_body():
    assert_readline("", None, "")
    assert_readline("", 1, "")


def test_readline_zero_size():
    assert_readline("abc", 0, "")
    assert_readline("\n", 0, "")


def test_readline_new_line_before_size():
    body = Body(StringIO("abc\ndef"))
    t.eq(body.readline(4), "abc\n")
    t.eq(body.readline(), "def")


def test_readline_new_line_after_size():
    body = Body(StringIO("abc\ndef"))
    t.eq(body.readline(2), "ab")
    t.eq(body.readline(), "c\n")


def test_readline_no_new_line():
    body = Body(StringIO("abcdef"))
    t.eq(body.readline(), "abcdef")
    body = Body(StringIO("abcdef"))
    t.eq(body.readline(2), "ab")
    t.eq(body.readline(2), "cd")
    t.eq(body.readline(2), "ef")


def test_readline_buffer_loaded():
    reader = StringIO("abc\ndef")
    body = Body(reader)
    body.read(1) # load internal buffer
    reader.write("g\nhi")
    reader.seek(7)
    t.eq(body.readline(), "bc\n")
    t.eq(body.readline(), "defg\n")
    t.eq(body.readline(), "hi")


def test_readline_buffer_loaded_with_size():
    body = Body(StringIO("abc\ndef"))
    body.read(1) # load internal buffer
    t.eq(body.readline(2), "bc")
    t.eq(body.readline(2), "\n")
    t.eq(body.readline(2), "de")
    t.eq(body.readline(2), "f")

