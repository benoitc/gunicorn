# -*- coding: utf-8 -

# Copyright 2013 Dariusz Suchojad <dsuch at zato.io>
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# stdlib
import inspect
import ssl
import sys
from unittest import TestCase

# gunicorn
from gunicorn.config import KeyFile, CertFile, SSLVersion, CACerts, \
     SuppressRaggedEOFs, DoHandshakeOnConnect, Setting, validate_bool, validate_string, \
     validate_pos_int

if sys.version_info >= (2, 7):
    from gunicorn.config import Ciphers

class SSLTestCase(TestCase):
    def test_settings_classes(self):
        """ Tests all settings options and their defaults.
        """
        self.assertTrue(issubclass(KeyFile, Setting))
        self.assertEquals(KeyFile.name, 'keyfile')
        self.assertEquals(KeyFile.section, 'Ssl')
        self.assertEquals(KeyFile.cli, ['--keyfile'])
        self.assertEquals(KeyFile.meta, 'FILE')
        self.assertEquals(KeyFile.default, None)

        self.assertTrue(issubclass(CertFile, Setting))
        self.assertEquals(CertFile.name, 'certfile')
        self.assertEquals(CertFile.section, 'Ssl')
        self.assertEquals(CertFile.cli, ['--certfile'])
        self.assertEquals(CertFile.default, None)
        
        self.assertTrue(issubclass(SSLVersion, Setting))
        self.assertEquals(SSLVersion.name, 'ssl_version')
        self.assertEquals(SSLVersion.section, 'Ssl')
        self.assertEquals(SSLVersion.cli, ['--ssl-version'])
        self.assertEquals(SSLVersion.default, ssl.PROTOCOL_TLSv1)
        
        self.assertTrue(issubclass(CACerts, Setting))
        self.assertEquals(CACerts.name, 'ca_certs')
        self.assertEquals(CACerts.section, 'Ssl')
        self.assertEquals(CACerts.cli, ['--ca-certs'])
        self.assertEquals(CACerts.meta, 'FILE')
        self.assertEquals(CACerts.default, None)

        self.assertTrue(issubclass(SuppressRaggedEOFs, Setting))
        self.assertEquals(SuppressRaggedEOFs.name, 'suppress_ragged_eofs')
        self.assertEquals(SuppressRaggedEOFs.section, 'Ssl')
        self.assertEquals(SuppressRaggedEOFs.cli, ['--suppress-ragged-eofs'])
        self.assertEquals(SuppressRaggedEOFs.action, 'store_true')
        self.assertEquals(SuppressRaggedEOFs.default, True)
        
        self.assertTrue(issubclass(DoHandshakeOnConnect, Setting))
        self.assertEquals(DoHandshakeOnConnect.name, 'do_handshake_on_connect')
        self.assertEquals(DoHandshakeOnConnect.section, 'Ssl')
        self.assertEquals(DoHandshakeOnConnect.cli, ['--do-handshake-on-connect'])
        self.assertEquals(DoHandshakeOnConnect.action, 'store_true')
        self.assertEquals(DoHandshakeOnConnect.default, False)


        if sys.version_info >= (2, 7):
            self.assertTrue(issubclass(Ciphers, Setting))        
            self.assertEquals(Ciphers.name, 'ciphers')
            self.assertEquals(Ciphers.section, 'Ssl')
            self.assertEquals(Ciphers.cli, ['--ciphers'])
            self.assertEquals(Ciphers.default, 'TLSv1')
