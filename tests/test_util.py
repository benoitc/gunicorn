# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import pytest

from gunicorn import util
from gunicorn.errors import AppImportError
from gunicorn.six.moves.urllib.parse import SplitResult  # pylint: disable=no-name-in-module
from socket import AF_INET
from socket import AF_INET6
from socket import AF_UNIX
from socket import SOCK_STREAM


@pytest.mark.parametrize('test_input, expected', [
    ('unix://var/run/test.sock', [(AF_UNIX, SOCK_STREAM, 0, '', 'var/run/test.sock')]),
    ('unix:/var/run/test.sock', [(AF_UNIX, SOCK_STREAM, 0, '', '/var/run/test.sock')]),
    #('', [(AF_INET6, SOCK_STREAM, 6, '', ('::', 8000, 0, 0))]),
    ('[::1]:8007', [(AF_INET6, SOCK_STREAM, 6, '', ('::1', 8007, 0, 0))]),
    #('localhost:8007', [(AF_INET6, SOCK_STREAM, 6, '', ('::1', 8007, 0, 0)),\
    #(AF_INET, SOCK_STREAM, 6, '', ('127.0.0.1', 8007))]),
    ('127.0.0.1:8007', [(AF_INET, SOCK_STREAM, 6, '', ('127.0.0.1', 8007))]),
    ('tcp://127.0.0.1:8007', [(AF_INET, SOCK_STREAM, 6, '', ('127.0.0.1', 8007))]),
    #('localhost', [(AF_INET6, SOCK_STREAM, 6, '', ('::1', 8000, 0, 0)),
    #(AF_INET, SOCK_STREAM, 6, '', ('127.0.0.1', 8000))])
])
def test_parse_address(test_input, expected):
    assert util.parse_address(test_input) == expected


def test_parse_address_invalid():
    with pytest.raises(RuntimeError) as err:
        util.parse_address('127.0.0.1:test')
    assert "'test' is not a valid port number." in str(err)


def test_http_date():
    assert util.http_date(1508607753.740316) == 'Sat, 21 Oct 2017 17:42:33 GMT'


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
