import datetime
import logging
from datetime import timedelta

from gunicorn.config import Config
from gunicorn.glogging import Logger

from support import SimpleNamespace

try:
    import unittest.mock as mock
except ImportError:
    import mock


def test_atoms_defaults():
    response = SimpleNamespace(
        status='200', response_length=1024,
        headers=(('Content-Type', 'application/json'),), sent=1024,
    )
    request = SimpleNamespace(headers=(('Accept', 'application/json'),))
    environ = {
        'REQUEST_METHOD': 'GET', 'RAW_URI': '/my/path?foo=bar',
        'PATH_INFO': '/my/path', 'QUERY_STRING': 'foo=bar',
        'SERVER_PROTOCOL': 'HTTP/1.1',
    }
    logger = Logger(Config())
    atoms = logger.atoms(response, request, environ, datetime.timedelta(seconds=1))
    assert isinstance(atoms, dict)
    assert atoms['r'] == 'GET /my/path?foo=bar HTTP/1.1'
    assert atoms['m'] == 'GET'
    assert atoms['U'] == '/my/path'
    assert atoms['q'] == 'foo=bar'
    assert atoms['H'] == 'HTTP/1.1'
    assert atoms['b'] == '1024'
    assert atoms['B'] == 1024
    assert atoms['{accept}i'] == 'application/json'
    assert atoms['{content-type}o'] == 'application/json'


def test_get_username_from_basic_auth_header():
    request = SimpleNamespace(headers=())
    response = SimpleNamespace(
        status='200', response_length=1024, sent=1024,
        headers=(('Content-Type', 'text/plain'),),
    )
    environ = {
        'REQUEST_METHOD': 'GET', 'RAW_URI': '/my/path?foo=bar',
        'PATH_INFO': '/my/path', 'QUERY_STRING': 'foo=bar',
        'SERVER_PROTOCOL': 'HTTP/1.1',
        'HTTP_AUTHORIZATION': 'Basic YnJrMHY6',
    }
    logger = Logger(Config())
    atoms = logger.atoms(response, request, environ, datetime.timedelta(seconds=1))
    assert atoms['u'] == 'brk0v'


def test_get_username_handles_malformed_basic_auth_header():
    """Should catch a malformed auth header"""
    request = SimpleNamespace(headers=())
    response = SimpleNamespace(
        status='200', response_length=1024, sent=1024,
        headers=(('Content-Type', 'text/plain'),),
    )
    environ = {
        'REQUEST_METHOD': 'GET', 'RAW_URI': '/my/path?foo=bar',
        'PATH_INFO': '/my/path', 'QUERY_STRING': 'foo=bar',
        'SERVER_PROTOCOL': 'HTTP/1.1',
        'HTTP_AUTHORIZATION': 'Basic ixsTtkKzIpVTncfQjbBcnoRNoDfbnaXG',
    }
    logger = Logger(Config())

    atoms = logger.atoms(response, request, environ, datetime.timedelta(seconds=1))
    assert atoms['u'] == '-'


@mock.patch("logging.getLogger")
def test_access_log_format_with_proper_atoms(mock_get_logger):
    response = SimpleNamespace(
        status='200', response_length=1024,
        headers=(('Content-Type', 'application/json'),), sent=1024,
    )
    request = SimpleNamespace(headers=(('Accept', 'application/json'),))
    environ = {
        'REQUEST_METHOD': 'GET', 'RAW_URI': '/my/path?foo=bar',
        'PATH_INFO': '/my/path', 'QUERY_STRING': 'foo=bar',
        'SERVER_PROTOCOL': 'HTTP/1.1',
    }
    mock_logger = mock.Mock()
    mock_logger.handlers = []
    mock_get_logger.return_value = mock_logger
    c = Config()
    c.set("accesslog", "-")
    c.set("access_log_format", '%(h)s %(l)s %(u)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"')
    logger = Logger(c)

    logger.access(response, request, environ, timedelta(seconds=1))
    mock_logger.info.assert_called_with('- - - "GET /my/path?foo=bar HTTP/1.1" 200 1024 "-" "-"')
