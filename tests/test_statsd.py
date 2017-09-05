from datetime import timedelta
import socket
import logging
import tempfile
import shutil
import os

from gunicorn.config import Config
from gunicorn.glogging import Logger, add_inst_methods
from gunicorn.instrument.statsd import Statsd
from gunicorn.six import StringIO

from support import SimpleNamespace

try:
    import unittest.mock as mock
except ImportError:
    import mock


class StatsdTestException(Exception):
    pass


class MockSocket(object):
    "Pretend to be a UDP socket"
    def __init__(self, failp):
        self.failp = failp
        self.msgs = []  # accumulate messages for later inspection

    def send(self, msg):
        if self.failp:
            raise StatsdTestException("Should not interrupt the logger")

        sock_dir = tempfile.mkdtemp()
        sock_file = os.path.join(sock_dir, "test.sock")

        server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)

        try:
            server.bind(sock_file)
            client.connect(sock_file)

            client.send(msg)
            self.msgs.append(server.recv(1024))

        finally:
            client.close()
            server.close()
            shutil.rmtree(sock_dir)

    def reset(self):
        self.msgs = []


def test_logger_creation():
    c = Config()
    c.set('statsd_host', 'localhost:12345')
    logger = Logger(c)
    assert isinstance(logger, Logger)


@mock.patch('time.strftime', return_value='01/Jan/2017:00:00:00 +0800')
def test_instrument(time_mock):
    c = Config()
    c.set('statsd_host', 'localhost:12345')
    c.set('accesslog', '-')
    statsd = Statsd(c)
    statsd.sock = MockSocket(False)
    add_inst_methods(Logger, statsd)
    logger = Logger(c)

    # Capture logged messages
    sio = StringIO()
    logger.error_log.handlers = [logging.StreamHandler(sio)]
    logger.access_log.handlers = [logging.StreamHandler(sio)]

    # Regular message
    logger.info("Blah", extra={"mtype": "gauge", "metric": "gunicorn.test", "value": 666})
    assert statsd.sock.msgs[0] == b"gunicorn.test:666|g"
    assert sio.getvalue() == "Blah\n"
    statsd.sock.reset()

    # Empty message
    logger.info("", extra={"mtype": "gauge", "metric": "gunicorn.test", "value": 666})
    assert statsd.sock.msgs[0] == b"gunicorn.test:666|g"
    assert sio.getvalue() == "Blah\n\n"  # Empty line is added from Logger.info
    statsd.sock.reset()

    # Debug with logger level: info (default)
    logger.debug("", extra={"mtype": "gauge", "metric": "gunicorn.debug", "value": 667})
    assert statsd.sock.msgs[0] == b"gunicorn.debug:667|g"
    assert sio.getvalue() == "Blah\n\n"  # Logging doesn't happen, but statsd still gets called
    statsd.sock.reset()

    # Critical
    logger.critical("Boom")
    assert statsd.sock.msgs[0] == b"gunicorn.log.critical:1|c|@1.0"
    assert sio.getvalue() == "Blah\n\nBoom\n"
    statsd.sock.reset()

    # Log with counter
    logger.log(logging.INFO, "Yay", extra={"mtype": "counter", "metric": "gunicorn.info", "value": 667})
    assert statsd.sock.msgs[0] == b"gunicorn.info:667|c|@1.0"
    assert sio.getvalue() == "Blah\n\nBoom\nYay\n"
    statsd.sock.reset()

    # Log with histogram
    logger.log(logging.INFO, "Wow", extra={"mtype": "histogram", "metric": "gunicorn.info", "value": 667})
    assert statsd.sock.msgs[0] == b"gunicorn.info:667|ms"
    assert sio.getvalue() == "Blah\n\nBoom\nYay\nWow\n"
    statsd.sock.reset()

    # Log with unknown
    logger.log(logging.INFO, "Wow", extra={"mtype": "unknown", "metric": "gunicorn.info", "value": 667})
    assert statsd.sock.msgs == []
    assert sio.getvalue() == "Blah\n\nBoom\nYay\nWow\nWow\n"
    statsd.sock.reset()

    # Access logging
    environ = {
        'REQUEST_METHOD': 'GET', 'RAW_URI': '/my/path?foo=bar',
        'PATH_INFO': '/my/path', 'QUERY_STRING': 'foo=bar',
        'SERVER_PROTOCOL': 'HTTP/1.1'
    }
    logger.access(SimpleNamespace(status="200 OK", headers=()), SimpleNamespace(headers=()), environ,
                  timedelta(seconds=7))
    assert statsd.sock.msgs[0] == b"gunicorn.request.duration:7000.0|ms"
    assert statsd.sock.msgs[1] == b"gunicorn.requests:1|c|@1.0"
    assert statsd.sock.msgs[2] == b"gunicorn.request.status.200:1|c|@1.0"
    assert sio.getvalue() == ('Blah\n\nBoom\nYay\nWow\nWow\n'
                              '- - - 01/Jan/2017:00:00:00 +0800 "GET /my/path?foo=bar HTTP/1.1" 200 - "-" "-"\n')
    statsd.sock.reset()

    # Exception
    logger.exception('exception')
    assert statsd.sock.msgs[0] == b"gunicorn.log.exception:1|c|@1.0"


def test_access_no_log():
    c = Config()
    c.set('statsd_host', 'localhost:12345')
    environ = {
        'REQUEST_METHOD': 'GET', 'RAW_URI': '/my/path?foo=bar',
        'PATH_INFO': '/my/path', 'QUERY_STRING': 'foo=bar',
        'SERVER_PROTOCOL': 'HTTP/1.1'
    }
    statsd = Statsd(c)
    statsd.sock = MockSocket(False)
    add_inst_methods(Logger, statsd)
    logger = Logger(c)

    # Capture logged messages
    sio = StringIO()
    logger.access_log.handlers = [logging.StreamHandler(sio)]

    logger.access(SimpleNamespace(status="200 OK", headers=()), SimpleNamespace(headers=()), environ,
                  timedelta(seconds=7))
    assert statsd.sock.msgs[0] == b"gunicorn.request.duration:7000.0|ms"
    assert statsd.sock.msgs[1] == b"gunicorn.requests:1|c|@1.0"
    assert statsd.sock.msgs[2] == b"gunicorn.request.status.200:1|c|@1.0"
    assert sio.getvalue() == ''


def test_prefix():
    c = Config()
    c.set('statsd_host', 'localhost:12345')
    c.set("statsd_prefix", "test.")
    statsd = Statsd(c)
    statsd.sock = MockSocket(False)
    add_inst_methods(Logger, statsd)
    logger = Logger(c)

    logger.info("Blah", extra={"mtype": "gauge", "metric": "gunicorn.test", "value": 666})
    assert statsd.sock.msgs[0] == b"test.gunicorn.test:666|g"


def test_prefix_no_dot():
    c = Config()
    c.set('statsd_host', 'localhost:12345')
    c.set("statsd_prefix", "test")
    statsd = Statsd(c)
    statsd.sock = MockSocket(False)
    add_inst_methods(Logger, statsd)
    logger = Logger(c)

    logger.info("Blah", extra={"mtype": "gauge", "metric": "gunicorn.test", "value": 666})
    assert statsd.sock.msgs[0] == b"test.gunicorn.test:666|g"


def test_prefix_multiple_dots():
    c = Config()
    c.set('statsd_host', 'localhost:12345')
    c.set("statsd_prefix", "test...")
    statsd = Statsd(c)
    statsd.sock = MockSocket(False)
    add_inst_methods(Logger, statsd)
    logger = Logger(c)

    logger.info("Blah", extra={"mtype": "gauge", "metric": "gunicorn.test", "value": 666})
    assert statsd.sock.msgs[0] == b"test.gunicorn.test:666|g"


def test_prefix_nested():
    c = Config()
    c.set('statsd_host', 'localhost:12345')
    c.set("statsd_prefix", "test.asdf.")
    statsd = Statsd(c)
    statsd.sock = MockSocket(False)
    add_inst_methods(Logger, statsd)
    logger = Logger(c)

    logger.info("Blah", extra={"mtype": "gauge", "metric": "gunicorn.test", "value": 666})
    assert statsd.sock.msgs[0] == b"test.asdf.gunicorn.test:666|g"


def test_statsd_no_sock():
    c = Config()
    c.set('statsd_host', 'localhost:12345')
    statsd = Statsd(c)
    statsd.sock = None
    add_inst_methods(Logger, statsd)
    logger = Logger(c)

    sio = StringIO()
    logger.error_log.handlers = [logging.StreamHandler(sio)]

    logger.log(logging.INFO, 'test-info')
    assert sio.getvalue() == "test-info\n"


@mock.patch('socket.socket.connect')
def test_statsd_fail_connect(connect_mock):
    connect_mock.side_effect = StatsdTestException()
    c = Config()
    c.set('statsd_host', 'localhost:12345')
    statsd = Statsd(c)
    assert statsd.sock is None


def test_statsd_fail():
    "UDP socket fails"
    c = Config()
    c.set('statsd_host', 'localhost:12345')
    statsd = Statsd(c)
    statsd.sock = MockSocket(True)
    add_inst_methods(Logger, statsd)
    logger = Logger(c)

    sio = StringIO()
    logger.error_log.handlers = [logging.StreamHandler(sio)]

    logger.info("test-info")
    assert sio.getvalue() == "test-info\n"
    logger.critical("test-critical")
    assert sio.getvalue() == "test-info\ntest-critical\n"
    logger.error("test-error")
    assert sio.getvalue() == "test-info\ntest-critical\ntest-error\n"
    logger.warning("test-warning")
    assert sio.getvalue() == "test-info\ntest-critical\ntest-error\ntest-warning\n"
