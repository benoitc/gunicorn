# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"Bare-bones implementation of statsD's protocol, client-side"
import re
import socket
import logging

from gunicorn.glogging import Logger

# Instrumentation constants
METRIC_VAR = "metric"
VALUE_VAR = "value"
MTYPE_VAR = "mtype"
GAUGE_TYPE = "gauge"
COUNTER_TYPE = "counter"
HISTOGRAM_TYPE = "histogram"


class Statsd:
    """statsD-based instrumentation, that passes as a logger
    """

    def __init__(self, prefix, host, port, tags):
        """host, port: statsD server
        """
        self.prefix = prefix_with_trailing_dot = re.sub(r"^(.+[^.]+)\.*$", "\\g<1>.",
                                                        prefix) if prefix is not None else ""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.connect((host, int(port)))
        except Exception:
            self.sock = None

        self.dogstatsd_tags = ",".join(tags)

    # access metric handling
    def access(self, resp, request_time):
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
        try:
            if isinstance(msg, str):
                msg = msg.encode("ascii")

            # http://docs.datadoghq.com/guides/dogstatsd/#datagram-format
            if self.dogstatsd_tags:
                msg = msg + b"|#" + self.dogstatsd_tags.encode('ascii')

            if self.sock:
                self.sock.send(msg)
        except Exception:
            # logging.getLogger(__name__).warning(self, "Error sending message to statsd", exc_info=True) # TODO
            pass
