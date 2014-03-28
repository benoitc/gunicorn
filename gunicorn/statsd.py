# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Bare-bones implementation of statsD's protocol, client-side
"""

import socket

# Instrumentation constants
STATSD_INTERVAL = 5 # publish stats every ... seconds
STATSD_DEFAULT_PORT = 8125

class statsd(object):
    def __init__(self, dst, log):
        """host, port: statsD server
        """
        try:
            self.log = log
            host, port = dst
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.connect((host, int(port)))
        except Exception, e:
            self.sock = None
            self.log.exception("Cannot connect to statsd server {0}".format(dst))

    def gauge(self, name, value):
        try:
            if self.sock:
                self.sock.send("%s:%s|g\n" % (name, value))
        except Exception:
            self.log.exception("Cannot send gauge")
    
    def increment(self, name, value):
        try:
            if self.sock:
                self.sock.send("%s:%s|c\n" % (name, value))
        except Exception:
            self.log.exception("Cannot send counter")


