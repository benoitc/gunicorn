# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import unittest
import pytest
aiohttp = pytest.importorskip("aiohttp")


from aiohttp.wsgi import WSGIServerHttpProtocol

import asyncio
from gunicorn.workers import gaiohttp
from gunicorn.config import Config
from unittest import mock


class WorkerTests(unittest.TestCase):

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(None)
        self.worker = gaiohttp.AiohttpWorker('age',
                                             'ppid',
                                             'sockets',
                                             'app',
                                             'timeout',
                                             Config(),
                                             'log')

    def tearDown(self):
        self.loop.close()

    @mock.patch('gunicorn.workers.gaiohttp.asyncio')
    def test_init_process(self, m_asyncio):
        try:
            self.worker.init_process()
        except TypeError:
            # to mask incomplete initialization of AiohttWorker instance:
            # we pass invalid values for ctor args
            pass

        self.assertTrue(m_asyncio.get_event_loop.return_value.close.called)
        self.assertTrue(m_asyncio.new_event_loop.called)
        self.assertTrue(m_asyncio.set_event_loop.called)

    @mock.patch('gunicorn.workers.gaiohttp.asyncio')
    def test_run(self, m_asyncio):
        self.worker.loop = mock.Mock()
        self.worker.run()

        self.assertTrue(m_asyncio.async.called)
        self.assertTrue(self.worker.loop.run_until_complete.called)
        self.assertTrue(self.worker.loop.close.called)

    def test_factory(self):
        self.worker.wsgi = mock.Mock()
        self.worker.loop = mock.Mock()
        self.worker.log = mock.Mock()
        self.worker.cfg = mock.Mock()

        f = self.worker.factory(
            self.worker.wsgi, ('localhost', 8080))
        self.assertIsInstance(f, WSGIServerHttpProtocol)

    @mock.patch('gunicorn.workers.gaiohttp.asyncio')
    def test__run(self, m_asyncio):
        self.worker.ppid = 1
        self.worker.alive = True
        self.worker.servers = []
        sock = mock.Mock()
        sock.cfg_addr = ('localhost', 8080)
        self.worker.sockets = [sock]
        self.worker.wsgi = mock.Mock()
        self.worker.log = mock.Mock()
        self.worker.notify = mock.Mock()
        loop = self.worker.loop = mock.Mock()
        loop.create_server.return_value = asyncio.Future(loop=self.loop)
        loop.create_server.return_value.set_result(sock)

        self.loop.run_until_complete(self.worker._run())

        self.assertTrue(self.worker.log.info.called)
        self.assertTrue(self.worker.notify.called)

    @mock.patch('gunicorn.workers.gaiohttp.asyncio')
    def test__run_unix_socket(self, m_asyncio):
        self.worker.ppid = 1
        self.worker.alive = True
        self.worker.servers = []
        sock = mock.Mock()
        sock.cfg_addr = '/tmp/gunicorn.sock'
        self.worker.sockets = [sock]
        self.worker.wsgi = mock.Mock()
        self.worker.log = mock.Mock()
        self.worker.notify = mock.Mock()
        loop = self.worker.loop = mock.Mock()
        loop.create_server.return_value = asyncio.Future(loop=self.loop)
        loop.create_server.return_value.set_result(sock)

        self.loop.run_until_complete(self.worker._run())

        self.assertTrue(self.worker.log.info.called)
        self.assertTrue(self.worker.notify.called)

    def test__run_connections(self):
        conn = mock.Mock()
        self.worker.ppid = 1
        self.worker.alive = False
        self.worker.servers = [mock.Mock()]
        self.worker.connections = {1: conn}
        self.worker.sockets = []
        self.worker.wsgi = mock.Mock()
        self.worker.log = mock.Mock()
        self.worker.loop = self.loop
        self.worker.loop.create_server = mock.Mock()
        self.worker.notify = mock.Mock()

        def _close_conns():
            self.worker.connections = {}

        self.loop.call_later(0.1, _close_conns)
        self.loop.run_until_complete(self.worker._run())

        self.assertTrue(self.worker.log.info.called)
        self.assertTrue(self.worker.notify.called)
        self.assertFalse(self.worker.servers)
        self.assertTrue(conn.closing.called)

    @mock.patch('gunicorn.workers.gaiohttp.os')
    @mock.patch('gunicorn.workers.gaiohttp.asyncio.sleep')
    def test__run_exc(self, m_sleep, m_os):
        m_os.getpid.return_value = 1
        m_os.getppid.return_value = 1

        self.worker.servers = [mock.Mock()]
        self.worker.ppid = 1
        self.worker.alive = True
        self.worker.sockets = []
        self.worker.log = mock.Mock()
        self.worker.loop = mock.Mock()
        self.worker.notify = mock.Mock()

        slp = asyncio.Future(loop=self.loop)
        slp.set_exception(KeyboardInterrupt)
        m_sleep.return_value = slp

        self.loop.run_until_complete(self.worker._run())
        self.assertTrue(m_sleep.called)
        self.assertTrue(self.worker.servers[0].close.called)

    def test_close_wsgi_app(self):
        self.worker.ppid = 1
        self.worker.alive = False
        self.worker.servers = [mock.Mock()]
        self.worker.connections = {}
        self.worker.sockets = []
        self.worker.log = mock.Mock()
        self.worker.loop = self.loop
        self.worker.loop.create_server = mock.Mock()
        self.worker.notify = mock.Mock()

        self.worker.wsgi = mock.Mock()
        self.worker.wsgi.close.return_value = asyncio.Future(loop=self.loop)
        self.worker.wsgi.close.return_value.set_result(1)

        self.loop.run_until_complete(self.worker._run())
        self.assertTrue(self.worker.wsgi.close.called)

        self.worker.wsgi = mock.Mock()
        self.worker.wsgi.close.return_value = asyncio.Future(loop=self.loop)
        self.worker.wsgi.close.return_value.set_exception(ValueError())

        self.loop.run_until_complete(self.worker._run())
        self.assertTrue(self.worker.wsgi.close.called)

    def test_wrp(self):
        conn = object()
        tracking = {}
        meth = mock.Mock()
        wrp = gaiohttp._wrp(conn, meth, tracking)
        wrp()

        self.assertIn(id(conn), tracking)
        self.assertTrue(meth.called)

        meth = mock.Mock()
        wrp = gaiohttp._wrp(conn, meth, tracking, False)
        wrp()

        self.assertNotIn(1, tracking)
        self.assertTrue(meth.called)
