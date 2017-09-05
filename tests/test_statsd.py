from datetime import timedelta
import socket
import logging
import tempfile
import shutil
import os
import mock

from gunicorn.config import Config
from gunicorn.glogging import Logger, add_inst_methods
from gunicorn.instrument.statsd import Statsd
from gunicorn.six import StringIO

from support import SimpleNamespace


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

    # Exception
    logger.exception("Exception")
    assert statsd.sock.msgs[0] == b"gunicorn.log.exception:1|c|@1.0"
    assert sio.getvalue() == "Blah\n\nBoom\nException\nNone\n"  # Exception adds exc_info (in this case None)
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
    assert sio.getvalue() == ('Blah\n\nBoom\nException\nNone\n'
                              '- - - 01/Jan/2017:00:00:00 +0800 "GET /my/path?foo=bar HTTP/1.1" 200 - "-" "-"\n')


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
    logger.exception("test-exception")
    assert sio.getvalue() == "test-info\ntest-critical\ntest-error\ntest-warning\ntest-exception\nNone\n"
