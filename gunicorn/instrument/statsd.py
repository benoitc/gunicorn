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
GAUGE_TYPE = "gauge"
COUNTER_TYPE = "counter"
HISTOGRAM_TYPE = "histogram"

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
        self._sanitize(kwargs)
        Logger.critical(self, msg, *args, **kwargs)
        self.increment("gunicorn.log.critical", 1)

    def error(self, msg, *args, **kwargs):
        self._sanitize(kwargs)
        Logger.error(self, msg, *args, **kwargs)
        self.increment("gunicorn.log.error", 1)

    def warning(self, msg, *args, **kwargs):
        self._sanitize(kwargs)
        Logger.warning(self, msg, *args, **kwargs)
        self.increment("gunicorn.log.warning", 1)

    def exception(self, msg, *args, **kwargs):
        self._sanitize(kwargs)
        Logger.exception(self, msg, *args, **kwargs)
        self.increment("gunicorn.log.exception", 1)

    # Special treatement for info, the most common log level
    def info(self, msg, *args, **kwargs):
        """Log a given statistic if metric, value and type are present
        """
        metric = kwargs.get(METRIC_VAR, None)
        value = kwargs.get(VALUE_VAR, None)
        typ = kwargs.get(MTYPE_VAR, None)
        if metric and value and typ:
            self._sanitize(kwargs)
            if typ == GAUGE_TYPE:
                self.gauge(metric, value)
            elif typ == COUNTER_TYPE:
                self.increment(metric, value)
            elif typ == HISTOGRAM_TYPE:
                self.histogram(metric, value)
            else:
                pass
        Logger.info(self, msg, *args, **kwargs)

    # skip the run-of-the-mill logs
    def debug(self, msg, *args, **kwargs):
        self._sanitize(kwargs)
        Logger.debug(self, msg, *args, **kwargs)

    def log(self, lvl, msg, *args, **kwargs):
        self._sanitize(kwargs)
        Logger.log(self, lvl, msg, *args, **kwargs)

    # access logging
    def access(self, resp, req, environ, request_time):
        """Measure request duration
        request_time is a datetime.timedelta
        """
        Logger.access(self, resp, req, environ, request_time)
        duration_in_s = request_time.seconds + float(request_time.microseconds)/10**6
        self.histogram("gunicorn.request.duration", duration_in_s)
        self.increment("gunicorn.requests", 1)

    def _sanitize(self, kwargs):
        """Drop stasd keywords from the logger"""
        for k in (METRIC_VAR, VALUE_VAR, MTYPE_VAR):
            try:
                kwargs.pop(k)
            except KeyError:
                pass

    # statsD methods
    def gauge(self, name, value):
        try:
            if self.sock:
                self.sock.send("{0}:{1}|g".format(name, value))
        except Exception:
            pass

    def increment(self, name, value, sampling_rate=1.0):
        try:
            if self.sock:
                self.sock.send("{0}:{1}|c|@{2}".format(name, value, sampling_rate))
        except Exception:
            pass

    def decrement(self, name, value, sampling_rate=1.0):
        try:
            if self.sock:
                self.sock.send("{0}:-{1}|c|@{2}".format(name, value, sampling_rate))
        except Exception:
            pass

    def histogram(self, name, value):
        try:
            if self.sock:
                self.sock.send("{0}:{1}|ms".format(name, value))
        except Exception:
            pass
