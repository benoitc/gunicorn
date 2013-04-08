import datetime

import t

from gunicorn.config import Config
from gunicorn.glogging import Logger


class Mock():
    def __init__(self, **kwargs):
        for attr in kwargs:
            setattr(self, attr, kwargs[attr])


def test_atoms_defaults():
    response = Mock(status='200', response_length=1024,
        headers=(('Content-Type', 'application/json'), ))
    request = Mock(headers=(('Accept', 'application/json'), ))
    environ = {'REQUEST_METHOD': 'GET', 'RAW_URI': 'http://my.uri',
        'SERVER_PROTOCOL': 'HTTP/1.1'}
    logger = Logger(Config())
    atoms = logger.atoms(response, request, environ,
        datetime.timedelta(seconds=1))
    t.istype(atoms, dict)
    t.eq(atoms['r'], 'GET http://my.uri HTTP/1.1')
    t.eq(atoms['{accept}i'], 'application/json')
    t.eq(atoms['{content-type}o'], 'application/json')
