# -*- coding: utf-8 -

# Copyright 2013 Dariusz Suchojad <dsuch at zato.io>
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import sys

import pytest

from gunicorn.config import (
    KeyFile, CertFile, SSLVersion, CACerts, SuppressRaggedEOFs,
    DoHandshakeOnConnect, Setting,
)

ssl = pytest.importorskip('ssl')


def test_keyfile():
    assert issubclass(KeyFile, Setting)
    assert KeyFile.name == 'keyfile'
    assert KeyFile.section == 'SSL'
    assert KeyFile.cli == ['--keyfile']
    assert KeyFile.meta == 'FILE'
    assert KeyFile.default is None


def test_certfile():
    assert issubclass(CertFile, Setting)
    assert CertFile.name == 'certfile'
    assert CertFile.section == 'SSL'
    assert CertFile.cli == ['--certfile']
    assert CertFile.default is None


def test_ssl_version():
    assert issubclass(SSLVersion, Setting)
    assert SSLVersion.name == 'ssl_version'
    assert SSLVersion.section == 'SSL'
    assert SSLVersion.cli == ['--ssl-version']
    assert SSLVersion.default == ssl.PROTOCOL_TLSv1


def test_cacerts():
    assert issubclass(CACerts, Setting)
    assert CACerts.name == 'ca_certs'
    assert CACerts.section == 'SSL'
    assert CACerts.cli == ['--ca-certs']
    assert CACerts.meta == 'FILE'
    assert CACerts.default is None


def test_suppress_ragged_eofs():
    assert issubclass(SuppressRaggedEOFs, Setting)
    assert SuppressRaggedEOFs.name == 'suppress_ragged_eofs'
    assert SuppressRaggedEOFs.section == 'SSL'
    assert SuppressRaggedEOFs.cli == ['--suppress-ragged-eofs']
    assert SuppressRaggedEOFs.action == 'store_true'
    assert SuppressRaggedEOFs.default is True


def test_do_handshake_on_connect():
    assert issubclass(DoHandshakeOnConnect, Setting)
    assert DoHandshakeOnConnect.name == 'do_handshake_on_connect'
    assert DoHandshakeOnConnect.section == 'SSL'
    assert DoHandshakeOnConnect.cli == ['--do-handshake-on-connect']
    assert DoHandshakeOnConnect.action == 'store_true'
    assert DoHandshakeOnConnect.default is False


@pytest.mark.skipif(sys.version_info < (2, 7),
                    reason="requires Python 2.7+")
def test_ciphers():
    from gunicorn.config import Ciphers

    assert issubclass(Ciphers, Setting)
    assert Ciphers.name == 'ciphers'
    assert Ciphers.section == 'SSL'
    assert Ciphers.cli == ['--ciphers']
    assert Ciphers.default == 'TLSv1'
