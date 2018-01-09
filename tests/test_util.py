# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import pytest

from gunicorn import util
from gunicorn.errors import AppImportError
from gunicorn.six.moves.urllib.parse import SplitResult  # pylint: disable=no-name-in-module


@pytest.mark.parametrize('test_input, expected', [
    ('unix://var/run/test.sock', 'var/run/test.sock'),
    ('unix:/var/run/test.sock', '/var/run/test.sock'),
    ('', ('0.0.0.0', 8000)),
    ('[::1]:8000', ('::1', 8000)),
    ('localhost:8000', ('localhost', 8000)),
    ('127.0.0.1:8000', ('127.0.0.1', 8000)),
    ('localhost', ('localhost', 8000))
])
def test_parse_address(test_input, expected):
    assert util.parse_address(test_input) == expected


def test_parse_address_invalid():
    with pytest.raises(RuntimeError) as err:
        util.parse_address('127.0.0.1:test')
    assert "'test' is not a valid port number." in str(err)


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


def test_import_app():
    assert util.import_app('support:app')

    with pytest.raises(ImportError) as err:
        util.import_app('a:app')
    assert 'No module' in str(err)

    with pytest.raises(AppImportError) as err:
        util.import_app('support:wrong_app')
    msg = "Failed to find application object 'wrong_app' in 'support'"
    assert msg in str(err)


def test_to_bytestring():
    assert util.to_bytestring('test_str', 'ascii') == b'test_str'
    assert util.to_bytestring('test_str®') == b'test_str\xc2\xae'
    assert util.to_bytestring(b'byte_test_str') == b'byte_test_str'
    with pytest.raises(TypeError) as err:
        util.to_bytestring(100)
    msg = '100 is not a string'
    assert msg in str(err)


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
