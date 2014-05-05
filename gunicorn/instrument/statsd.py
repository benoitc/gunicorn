# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Bare-bones implementation of statsD's protocol, client-side
"""
import socket
from gunicorn.glogging import Logger

# Instrumentation constants
STATSD_DEFAULT_PORT = 8125
METRIC_VAR = "metric"
VALUE_VAR = "value"
MTYPE_VAR = "mtype"
SAMPLING_VAR = "sampling"

class Statsd(Logger):
    """statsD-based instrumentation, that passes as a logger
    """
    def __init__(self, cfg):
        """host, port: statsD server
        """
        Logger.__init__(self, cfg)
        try:
            host, port = cfg.statsd_to
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.connect((host, int(port)))
        except Exception:
            self.sock = None

    # Log errors and warnings
    def critical(self, msg, *args, **kwargs):
        Logger.critical(self, msg, *args, **kwargs)
        self.increment("gunicorn.log.critical", 1)

    def error(self, msg, *args, **kwargs):
        Logger.error(self, msg, *args, **kwargs)
        self.increment("gunicorn.log.error", 1)

    def warning(self, msg, *args, **kwargs):
        Logger.warning(self, msg, *args, **kwargs)
        self.increment("gunicorn.log.warning", 1)

    def exception(self, msg, *args, **kwargs):
        Logger.exception(self, msg, *args, **kwargs)
        self.increment("gunicorn.log.exception", 1)

    def info(self, msg, *args, **kwargs):
        """Log a given statistic if metric, value, sampling are present
        """
        Logger.info(self, msg, *args, **kwargs)
        metric = kwargs.get(METRIC_VAR, None)
        value = kwargs.get(VALUE_VAR, None)
        typ = kwargs.get(MTYPE_VAR, None)
        if metric and value and typ:
            if typ == "gauge":
                self.gauge(metric, value)
            elif typ == "counter":
                sampling = kwargs.get(SAMPLING_VAR, 1.0)
                self.increment(metric, value, sampling)
            else:
                pass

    # skip the run-of-the-mill logs
    def debug(self, msg, *args, **kwargs):
        Logger.debug(self, msg, *args, **kwargs)

    def log(self, lvl, msg, *args, **kwargs):
        Logger.log(self, lvl, msg, *args, **kwargs)

    # access logging
    def access(self, resp, req, environ, request_time):
        """Measure request duration
        """
        Logger.access(self, resp, req, environ, request_time)
        self.histogram("gunicorn.request.duration", request_time)
        self.increment("gunicorn.requests", 1)

    # statsD methods
    def gauge(self, name, value):
        try:
            if self.sock:
                self.sock.send("%s:%s|g\n" % (name, value))
        except Exception:
            pass

    def increment(self, name, value, sampling_rate=1.0):
        try:
            if self.sock:
                self.sock.send("%s:%s|c@%s\n" % (name, value, sampling_rate))
        except Exception:
            pass

    def decrement(self, name, value, sampling_rate=1.0):
        try:
            if self.sock:
                self.sock.send("%s:-%s|c@%s\n" % (name, value, sampling_rate))
        except Exception:
            pass

    def histogram(self, name, value, sampling_rate=1.0):
        try:
            if self.sock:
                self.sock.send("%s:%s|h@%s\n" % (name, value, sampling_rate))
        except Exception:
            pass
