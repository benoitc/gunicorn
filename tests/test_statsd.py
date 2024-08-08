import io
import logging
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


class MockSocket:
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
    logger.info("No impact on logging")
    logger.debug("No impact on logging")
    logger.critical("No impact on logging")
    logger.error("No impact on logging")
    logger.warning("No impact on logging")
    logger.exception("No impact on logging")


def test_statsd_host_initialization():
    c = Config()
    c.set('statsd_host', 'unix:test.sock')
    logger = Statsd(c)
    logger.info("Can be initialized and used with a UDS socket")

    # Can be initialized and used with a UDP address
    c.set('statsd_host', 'host:8080')
    logger = Statsd(c)
    logger.info("Can be initialized and used with a UDP socket")


def test_dogstatsd_tags():
    c = Config()
    tags = 'yucatan,libertine:rhubarb'
    c.set('dogstatsd_tags', tags)
    logger = Statsd(c)
    logger.sock = MockSocket(False)
    logger.info("Twill", extra={"mtype": "gauge", "metric": "barb.westerly",
                                "value": 2})
    assert logger.sock.msgs[0] == b"barb.westerly:2|g|#" + tags.encode('ascii')


def test_instrument():
    logger = Statsd(Config())
    # Capture logged messages
    sio = io.StringIO()
    logger.error_log.addHandler(logging.StreamHandler(sio))
    logger.sock = MockSocket(False)

    # Regular message
    logger.info("Blah", extra={"mtype": "gauge", "metric": "gunicorn.test", "value": 666})
    assert logger.sock.msgs[0] == b"gunicorn.test:666|g"
    assert sio.getvalue() == "Blah\n"
    logger.sock.reset()

    # Only metrics, no logging
    logger.info("", extra={"mtype": "gauge", "metric": "gunicorn.test", "value": 666})
    assert logger.sock.msgs[0] == b"gunicorn.test:666|g"
    assert sio.getvalue() == "Blah\n"  # log is unchanged
    logger.sock.reset()

    # Debug logging also supports metrics
    logger.debug("", extra={"mtype": "gauge", "metric": "gunicorn.debug", "value": 667})
    assert logger.sock.msgs[0] == b"gunicorn.debug:667|g"
    assert sio.getvalue() == "Blah\n"  # log is unchanged
    logger.sock.reset()

    logger.critical("Boom")
    assert logger.sock.msgs[0] == b"gunicorn.log.critical:1|c|@1.0"
    logger.sock.reset()

    logger.access(SimpleNamespace(status="200 OK"), None, {}, timedelta(seconds=7))
    assert logger.sock.msgs[0] == b"gunicorn.request.duration:7000.0|ms"
    assert logger.sock.msgs[1] == b"gunicorn.requests:1|c|@1.0"
    assert logger.sock.msgs[2] == b"gunicorn.request.status.200:1|c|@1.0"


def test_prefix():
    c = Config()
    c.set("statsd_prefix", "test.")
    logger = Statsd(c)
    logger.sock = MockSocket(False)

    logger.info("Blah", extra={"mtype": "gauge", "metric": "gunicorn.test", "value": 666})
    assert logger.sock.msgs[0] == b"test.gunicorn.test:666|g"


def test_prefix_no_dot():
    c = Config()
    c.set("statsd_prefix", "test")
    logger = Statsd(c)
    logger.sock = MockSocket(False)

    logger.info("Blah", extra={"mtype": "gauge", "metric": "gunicorn.test", "value": 666})
    assert logger.sock.msgs[0] == b"test.gunicorn.test:666|g"


def test_prefix_multiple_dots():
    c = Config()
    c.set("statsd_prefix", "test...")
    logger = Statsd(c)
    logger.sock = MockSocket(False)

    logger.info("Blah", extra={"mtype": "gauge", "metric": "gunicorn.test", "value": 666})
    assert logger.sock.msgs[0] == b"test.gunicorn.test:666|g"


def test_prefix_nested():
    c = Config()
    c.set("statsd_prefix", "test.asdf.")
    logger = Statsd(c)
    logger.sock = MockSocket(False)

    logger.info("Blah", extra={"mtype": "gauge", "metric": "gunicorn.test", "value": 666})
    assert logger.sock.msgs[0] == b"test.asdf.gunicorn.test:666|g"
