# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import datetime
import logging
logging.Logger.manager.emittedNoHandlerWarning = 1
from logging.config import fileConfig
import os
import socket
import sys
import traceback
import threading


from gunicorn import util
from gunicorn.six import string_types


# syslog facility codes
SYSLOG_FACILITIES = {
        "auth":     4,
        "authpriv": 10,
        "cron":     9,
        "daemon":   3,
        "ftp":      11,
        "kern":     0,
        "lpr":      6,
        "mail":     2,
        "news":     7,
        "security": 4,  #  DEPRECATED
        "syslog":   5,
        "user":     1,
        "uucp":     8,
        "local0":   16,
        "local1":   17,
        "local2":   18,
        "local3":   19,
        "local4":   20,
        "local5":   21,
        "local6":   22,
        "local7":   23
        }


CONFIG_DEFAULTS = dict(
        version=1,
        disable_existing_loggers=False,

        loggers={
            "root": {"level": "INFO", "handlers": ["console"]},
            "gunicorn.error": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": True,
                "qualname": "gunicorn.error"
            }
        },
        handlers={
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "generic",
                "stream": "sys.stdout"
            }
        },
        formatters={
            "generic": {
                "format": "%(asctime)s [%(process)d] [%(levelname)s] %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
                "class": "logging.Formatter"
            }
        }
)


def loggers():
    """ get list of all loggers """
    root = logging.root
    existing = root.manager.loggerDict.keys()
    return [logging.getLogger(name) for name in existing]


class LazyWriter(object):

    """
    File-like object that opens a file lazily when it is first written
    to.
    """

    def __init__(self, filename, mode='w'):
        self.filename = filename
        self.fileobj = None
        self.lock = threading.Lock()
        self.mode = mode

    def open(self):
        if self.fileobj is None:
            self.lock.acquire()
            try:
                if self.fileobj is None:
                    self.fileobj = open(self.filename, self.mode)
            finally:
                self.lock.release()
        return self.fileobj

    def close(self):
        if self.fileobj:
            self.lock.acquire()
            try:
                if self.fileobj:
                    self.fileobj.close()
                    self.fileobj = None
            finally:
                self.lock.release()

    def write(self, text):
        fileobj = self.open()
        fileobj.write(text)
        fileobj.flush()

    def writelines(self, text):
        fileobj = self.open()
        fileobj.writelines(text)
        fileobj.flush()

    def flush(self):
        self.open().flush()

    def isatty(self):
        return bool(self.fileobj and self.fileobj.isatty())


class SafeAtoms(dict):

    def __init__(self, atoms):
        dict.__init__(self)
        for key, value in atoms.items():
            self[key] = value.replace('"', '\\"')

    def __getitem__(self, k):
        if k.startswith("{"):
            kl = k.lower()
            if kl in self:
                return super(SafeAtoms, self).__getitem__(kl)
            else:
                return "-"
        if k in self:
            return super(SafeAtoms, self).__getitem__(k)
        else:
            return '-'


def parse_syslog_address(addr):

    if addr.startswith("unix://"):
        return (socket.SOCK_STREAM, addr.split("unix://")[1])

    if addr.startswith("udp://"):
        addr = addr.split("udp://")[1]
        socktype = socket.SOCK_DGRAM
    elif addr.startswith("tcp://"):
        addr = addr.split("tcp://")[1]
        socktype = socket.SOCK_STREAM
    else:
        raise RuntimeError("invalid syslog address")

    if '[' in addr and ']' in addr:
        host = addr.split(']')[0][1:].lower()
    elif ':' in addr:
        host = addr.split(':')[0].lower()
    elif addr == "":
        host = "localhost"
    else:
        host = addr.lower()

    addr = addr.split(']')[-1]
    if ":" in addr:
        port = addr.split(':', 1)[1]
        if not port.isdigit():
            raise RuntimeError("%r is not a valid port number." % port)
        port = int(port)
    else:
        port = 514

    return (socktype, (host, port))


class Logger(object):

    LOG_LEVELS = {
        "critical": logging.CRITICAL,
        "error": logging.ERROR,
        "warning": logging.WARNING,
        "info": logging.INFO,
        "debug": logging.DEBUG
    }

    error_fmt = r"%(asctime)s [%(process)d] [%(levelname)s] %(message)s"
    datefmt = r"%Y-%m-%d %H:%M:%S"

    access_fmt = "%(message)s"
    syslog_fmt = "[%(process)d] %(message)s"

    def __init__(self, cfg):
        self.error_log = logging.getLogger("gunicorn.error")
        self.access_log = logging.getLogger("gunicorn.access")
        self.error_handlers = []
        self.access_handlers = []
        self.cfg = cfg
        self.setup(cfg)

    def setup(self, cfg):
        if not cfg.logconfig:
            loglevel = self.LOG_LEVELS.get(cfg.loglevel.lower(), logging.INFO)
            self.error_log.setLevel(loglevel)
            self.access_log.setLevel(logging.INFO)

            if cfg.errorlog != "-":
                # if an error log file is set redirect stdout & stderr to
                # this log file.
                sys.stdout = sys.stderr = LazyWriter(cfg.errorlog, 'a')

            # set gunicorn.error handler
            self._set_handler(self.error_log, cfg.errorlog,
                    logging.Formatter(self.error_fmt, self.datefmt))

            # set gunicorn.access handler
            if cfg.accesslog is not None:
                self._set_handler(self.access_log, cfg.accesslog,
                    fmt=logging.Formatter(self.access_fmt))

            # set syslog handler
            if cfg.syslog:
                self._set_syslog_handler(self.error_log, cfg, self.syslog_fmt)

        else:
            if os.path.exists(cfg.logconfig):
                fileConfig(cfg.logconfig, defaults=CONFIG_DEFAULTS,
                        disable_existing_loggers=False)
            else:
                raise RuntimeError("Error: log config '%s' not found" % cfg.logconfig)

    def critical(self, msg, *args, **kwargs):
        self.error_log.critical(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self.error_log.error(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self.error_log.warning(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self.error_log.info(msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        self.error_log.debug(msg, *args, **kwargs)

    def exception(self, msg, *args):
        self.error_log.exception(msg, *args)

    def log(self, lvl, msg, *args, **kwargs):
        if isinstance(lvl, string_types):
            lvl = self.LOG_LEVELS.get(lvl.lower(), logging.INFO)
        self.error_log.log(lvl, msg, *args, **kwargs)

    def access(self, resp, req, environ, request_time):
        """ Seee http://httpd.apache.org/docs/2.0/logs.html#combined
        for format details
        """

        if not self.cfg.accesslog and not self.cfg.logconfig:
            return

        status = resp.status.split(None, 1)[0]
        atoms = {
                'h': environ.get('REMOTE_ADDR', '-'),
                'l': '-',
                'u': '-',  # would be cool to get username from basic auth header
                't': self.now(),
                'r': "%s %s %s" % (environ['REQUEST_METHOD'],
                    environ['RAW_URI'], environ["SERVER_PROTOCOL"]),
                's': status,
                'b': resp.response_length and str(resp.response_length) or '-',
                'f': environ.get('HTTP_REFERER', '-'),
                'a': environ.get('HTTP_USER_AGENT', '-'),
                'T': str(request_time.seconds),
                'D': str(request_time.microseconds),
                'p': "<%s>" % os.getpid()
                }

        # add request headers
        if hasattr(req, 'headers'):
            req_headers = req.headers
        else:
            req_headers = req

        atoms.update(dict([("{%s}i" % k.lower(), v) for k, v in req_headers]))

        # add response headers
        atoms.update(dict([("{%s}o" % k.lower(), v) for k, v in resp.headers]))

        # wrap atoms:
        # - make sure atoms will be test case insensitively
        # - if atom doesn't exist replace it by '-'
        safe_atoms = SafeAtoms(atoms)

        try:
            self.access_log.info(self.cfg.access_log_format % safe_atoms)
        except:
            self.error(traceback.format_exc())

    def now(self):
        """ return date in Apache Common Log Format """
        now = datetime.datetime.now()
        month = util.monthname[now.month]
        return '[%02d/%s/%04d:%02d:%02d:%02d]' % (now.day, month,
                now.year, now.hour, now.minute, now.second)

    def reopen_files(self):
        if self.cfg.errorlog != "-":
            # Close stderr & stdout if they are redirected to error log file
            sys.stderr.close()
            sys.stdout.close()
        for log in loggers():
            for handler in log.handlers:
                if isinstance(handler, logging.FileHandler):
                    handler.acquire()
                    try:
                        if handler.stream:
                            handler.stream.close()
                            handler.stream = open(handler.baseFilename,
                                    handler.mode)
                    finally:
                        handler.release()

    def close_on_exec(self):
        for log in loggers():
            for handler in log.handlers:
                if isinstance(handler, logging.FileHandler):
                    handler.acquire()
                    try:
                        if handler.stream:
                            util.close_on_exec(handler.stream.fileno())
                    finally:
                        handler.release()

    def _get_gunicorn_handler(self, log):
        for h in log.handlers:
            if getattr(h, "_gunicorn", False) == True:
                return h

    def _set_handler(self, log, output, fmt):
        # remove previous gunicorn log handler
        h = self._get_gunicorn_handler(log)
        if h:
            log.handlers.remove(h)

        if output == "-":
            h = logging.StreamHandler()
        else:
            util.check_is_writeable(output)
            h = logging.FileHandler(output)

        h.setFormatter(fmt)
        h._gunicorn = True
        log.addHandler(h)

    def _set_syslog_handler(self, log, cfg, fmt):
        # setup format
        if not cfg.syslog_prefix:
            prefix = cfg.proc_name.replace(":", ".")
        else:
            prefix = cfg.syslog_prefix

        prefix = "gunicorn.%s" % prefix

        # set format
        fmt = logging.Formatter(r"%s: %s" % (prefix, fmt))

        # syslog facility
        try:
            facility = SYSLOG_FACILITIES[cfg.syslog_facility.lower()]
        except KeyError:
            raise RuntimeError("unknown facility name")

        # parse syslog address
        socktype, addr = parse_syslog_address(cfg.syslog_addr)

        # finally setup the syslog handler
        h = logging.handlers.SysLogHandler(address=addr, facility=facility,
                socktype=socktype)
        h.setFormatter(fmt)
        h._gunicorn = True
        log.addHandler(h)
