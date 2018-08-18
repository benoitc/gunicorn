# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"Bare-bones implementation of statsD's protocol, client-side"
import socket
from re import sub

from gunicorn import six

# Instrumentation constants
METRIC_VAR = "metric"
VALUE_VAR = "value"
MTYPE_VAR = "mtype"
GAUGE_TYPE = "gauge"
COUNTER_TYPE = "counter"
HISTOGRAM_TYPE = "histogram"


class Statsd(object):
    """
    Statsd instrumentation.
    Logging methods (critical, error, warning, exception, info, debug, log,
    access) will get wrapped in glogging._wrap_log_method by
    glogging.add_inst_methods, receiving logger and arguments.
    """

    def __init__(self, cfg):
        """host, port: statsD server
        """
        self.prefix = sub(r"^(.+[^.]+)\.*$", "\\g<1>.", cfg.statsd_prefix)
        host, port = cfg.statsd_host
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.connect((host, int(port)))

    # Log errors and warnings
    def critical(self, *args, **kwargs):
        self.increment("gunicorn.log.critical", 1)

    def error(self, *args, **kwargs):
        self.increment("gunicorn.log.error", 1)

    def warning(self, *args, **kwargs):
        self.increment("gunicorn.log.warning", 1)

    def exception(self, *args, **kwargs):
        self.increment("gunicorn.log.exception", 1)

    # Special treatement for info, the most common log level
    def info(self, *args, **kwargs):
        self.log(*args, **kwargs)

    # skip the run-of-the-mill logs
    def debug(self, *args, **kwargs):
        self.log(*args, **kwargs)

    def log(self, *args, **kwargs):
        """Log a given statistic if metric, value and type are present
        """
        extra = kwargs.get("extra", None)
        if extra is not None:
            metric = extra.get(METRIC_VAR, None)
            value = extra.get(VALUE_VAR, None)
            typ = extra.get(MTYPE_VAR, None)
            if metric and value and typ:
                if typ == GAUGE_TYPE:
                    self.gauge(metric, value)
                elif typ == COUNTER_TYPE:
                    self.increment(metric, value)
                elif typ == HISTOGRAM_TYPE:
                    self.histogram(metric, value)

    # access logging
    def access(self, resp, req, environ, request_time):
        """Measure request duration
        request_time is a datetime.timedelta
        """
        duration_in_ms = request_time.seconds * 1000 + float(request_time.microseconds) / 10 ** 3
        status = resp.status
        if isinstance(status, str):
            status = int(status.split(None, 1)[0])
        self.histogram("gunicorn.request.duration", duration_in_ms)
        self.increment("gunicorn.requests", 1)
        self.increment("gunicorn.request.status.%d" % status, 1)

    # statsD methods
    # you can use those directly if you want
    def gauge(self, name, value):
        self._sock_send("{0}{1}:{2}|g".format(self.prefix, name, value))

    def increment(self, name, value, sampling_rate=1.0):
        self._sock_send("{0}{1}:{2}|c|@{3}".format(self.prefix, name, value, sampling_rate))

    def decrement(self, name, value, sampling_rate=1.0):
        self._sock_send("{0}{1}:-{2}|c|@{3}".format(self.prefix, name, value, sampling_rate))

    def histogram(self, name, value):
        self._sock_send("{0}{1}:{2}|ms".format(self.prefix, name, value))

    def _sock_send(self, msg):
        if isinstance(msg, six.text_type):
            msg = msg.encode("ascii")
        if self.sock:
            self.sock.send(msg)
        else:
            raise Exception("Statsd connection is not initialized")
