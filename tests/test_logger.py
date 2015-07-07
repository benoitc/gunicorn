import datetime

import t

from gunicorn.config import Config
from gunicorn.glogging import Logger

from support import SimpleNamespace


def test_atoms_defaults():
    response = SimpleNamespace(
        status='200', response_length=1024,
        headers=(('Content-Type', 'application/json'),), sent=1024,
    )
    request = SimpleNamespace(headers=(('Accept', 'application/json'),))
    environ = {
        'REQUEST_METHOD': 'GET', 'RAW_URI': 'http://my.uri',
        'SERVER_PROTOCOL': 'HTTP/1.1',
    }
    logger = Logger(Config())
    atoms = logger.atoms(response, request, environ, datetime.timedelta(seconds=1))
    assert isinstance(atoms, dict)
    assert atoms['r'] == 'GET http://my.uri HTTP/1.1'
    assert atoms['{accept}i'] == 'application/json'
    assert atoms['{content-type}o'] == 'application/json'
