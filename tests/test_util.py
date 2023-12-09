#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.
import os

import pytest

from gunicorn import util
from gunicorn.errors import AppImportError
from urllib.parse import SplitResult


@pytest.mark.parametrize('test_input, expected', [
    ('unix://var/run/test.sock', 'var/run/test.sock'),
    ('unix:/var/run/test.sock', '/var/run/test.sock'),
    ('tcp://localhost', ('localhost', 8000)),
    ('tcp://localhost:5000', ('localhost', 5000)),
    ('', ('0.0.0.0', 8000)),
    ('[::1]:8000', ('::1', 8000)),
    ('[::1]:5000', ('::1', 5000)),
    ('[::1]', ('::1', 8000)),
    ('localhost:8000', ('localhost', 8000)),
    ('127.0.0.1:8000', ('127.0.0.1', 8000)),
    ('localhost', ('localhost', 8000)),
    ('fd://33', 33),
])
def test_parse_address(test_input, expected):
    assert util.parse_address(test_input) == expected


def test_parse_address_invalid():
    with pytest.raises(RuntimeError) as exc_info:
        util.parse_address('127.0.0.1:test')
    assert "'test' is not a valid port number." in str(exc_info.value)


def test_parse_fd_invalid():
    with pytest.raises(RuntimeError) as exc_info:
        util.parse_address('fd://asd')
    assert "'asd' is not a valid file descriptor." in str(exc_info.value)


def test_http_date():
    assert util.http_date(1508607753.740316) == 'Sat, 21 Oct 2017 17:42:33 GMT'


@pytest.mark.parametrize('test_input, expected', [
    ('1200:0000:AB00:1234:0000:2552:7777:1313', True),
    ('1200::AB00:1234::2552:7777:1313', False),
    ('21DA:D3:0:2F3B:2AA:FF:FE28:9C5A', True),
    ('1200:0000:AB00:1234:O000:2552:7777:1313', False),
])
def test_is_ipv6(test_input, expected):
    assert util.is_ipv6(test_input) == expected


def test_warn(capsys):
    util.warn('test warn')
    _, err = capsys.readouterr()
    assert '!!! WARNING: test warn' in err


@pytest.mark.parametrize(
    "value",
    [
        "support",
        "support:app",
        "support:create_app()",
        "support:create_app('Gunicorn', 3)",
        "support:create_app(count=3)",
    ],
)
def test_import_app_good(value):
    assert util.import_app(value)


@pytest.mark.parametrize(
    ("value", "exc_type", "msg"),
    [
        ("a:app", ImportError, "No module"),
        ("support:create_app(", AppImportError, "Failed to parse"),
        ("support:create.app()", AppImportError, "Function reference"),
        ("support:create_app(Gunicorn)", AppImportError, "literal values"),
        ("support:create.app", AppImportError, "attribute name"),
        ("support:wrong_app", AppImportError, "find attribute"),
        ("support:error_factory(1)", AppImportError, "error_factory() takes"),
        ("support:error_factory()", TypeError, "inner"),
        ("support:none_app", AppImportError, "find application object"),
        ("support:HOST", AppImportError, "callable"),
    ],
)
def test_import_app_bad(value, exc_type, msg):
    with pytest.raises(exc_type) as exc_info:
        util.import_app(value)

    assert msg in str(exc_info.value)


def test_import_app_py_ext(monkeypatch):
    monkeypatch.chdir(os.path.dirname(__file__))

    with pytest.raises(ImportError) as exc_info:
        util.import_app("support.py")

    assert "did you mean" in str(exc_info.value)


def test_to_bytestring():
    assert util.to_bytestring('test_str', 'ascii') == b'test_str'
    assert util.to_bytestring('test_str®') == b'test_str\xc2\xae'
    assert util.to_bytestring(b'byte_test_str') == b'byte_test_str'
    with pytest.raises(TypeError) as exc_info:
        util.to_bytestring(100)
    msg = '100 is not a string'
    assert msg in str(exc_info.value)


@pytest.mark.parametrize('test_input, expected', [
    ('https://example.org/a/b?c=1#d',
     SplitResult(scheme='https', netloc='example.org', path='/a/b', query='c=1', fragment='d')),
    ('a/b?c=1#d',
     SplitResult(scheme='', netloc='', path='a/b', query='c=1', fragment='d')),
    ('/a/b?c=1#d',
     SplitResult(scheme='', netloc='', path='/a/b', query='c=1', fragment='d')),
    ('//a/b?c=1#d',
     SplitResult(scheme='', netloc='', path='//a/b', query='c=1', fragment='d')),
    ('///a/b?c=1#d',
     SplitResult(scheme='', netloc='', path='///a/b', query='c=1', fragment='d')),
])
def test_split_request_uri(test_input, expected):
    assert util.split_request_uri(test_input) == expected
