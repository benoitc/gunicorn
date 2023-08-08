import os
import shutil
import socket
import tempfile
from datetime import timedelta
from types import SimpleNamespace

from gunicorn.config import Config
from gunicorn.instrument.statsd import Statsd


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


def test_statsd_fail():
    "UDP socket fails"
    logger = Statsd(Config())
    logger.sock = MockSocket(True)
    logger.increment("No impact on logging", 1)
    logger.decrement("No impact on logging", 1)
    logger.histogram("No impact on logging", 5)
    logger.gauge("No impact on logging", 10)


def test_statsd_host_initialization():
    c = Config()
    c.set('statsd_host', 'unix:test.sock')
    logger = Statsd(c)
    logger.increment("Can be initialized and used with a UDS socket", 1)

    # Can be initialized and used with a UDP address
    c.set('statsd_host', 'host:8080')
    logger = Statsd(c)
    logger.increment("Can be initialized and used with a UDP socket", 1)


def test_dogstatsd_tags():
    c = Config()
    tags = 'yucatan,libertine:rhubarb'
    c.set('dogstatsd_tags', tags)
    logger = Statsd(c)
    logger.sock = MockSocket(False)
    logger.gauge("barb.westerly", 2)
    assert logger.sock.msgs[0] == b"barb.westerly:2|g|#" + tags.encode('ascii')


def test_instrument():
    logger = Statsd(Config())
    # Capture logged messages
    logger.sock = MockSocket(False)

    # Regular message
    logger.gauge("gunicorn.test", 666)
    assert logger.sock.msgs[0] == b"gunicorn.test:666|g"
    logger.sock.reset()

    logger.access(SimpleNamespace(status="200 OK"), timedelta(seconds=7))
    assert logger.sock.msgs[0] == b"gunicorn.request.duration:7000.0|ms"
    assert logger.sock.msgs[1] == b"gunicorn.requests:1|c|@1.0"
    assert logger.sock.msgs[2] == b"gunicorn.request.status.200:1|c|@1.0"


def test_prefix():
    c = Config()
    c.set("statsd_prefix", "test.")
    logger = Statsd(c)
    logger.sock = MockSocket(False)

    logger.gauge("gunicorn.test", 666)
    assert logger.sock.msgs[0] == b"test.gunicorn.test:666|g"


def test_prefix_no_dot():
    c = Config()
    c.set("statsd_prefix", "test")
    logger = Statsd(c)
    logger.sock = MockSocket(False)

    logger.gauge("gunicorn.test", 666)
    assert logger.sock.msgs[0] == b"test.gunicorn.test:666|g"


def test_prefix_multiple_dots():
    c = Config()
    c.set("statsd_prefix", "test...")
    logger = Statsd(c)
    logger.sock = MockSocket(False)

    logger.gauge("gunicorn.test", 666)
    assert logger.sock.msgs[0] == b"test.gunicorn.test:666|g"


def test_prefix_nested():
    c = Config()
    c.set("statsd_prefix", "test.asdf.")
    logger = Statsd(c)
    logger.sock = MockSocket(False)

    logger.gauge("gunicorn.test", 666)
    assert logger.sock.msgs[0] == b"test.asdf.gunicorn.test:666|g"
