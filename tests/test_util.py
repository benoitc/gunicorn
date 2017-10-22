# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import pytest

from gunicorn import util


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
        assert util.parse_address('127.0.0.1:test')
    assert "'test' is not a valid port number." in str(err)
