# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from gunicorn import util


def test_parse_address():
    # Test unix socket addresses (PR #1623)
    assert util.parse_address('unix://var/run/test.sock') == 'var/run/test.sock'
    assert util.parse_address('unix:/var/run/test.sock') == '/var/run/test.sock'
