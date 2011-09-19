# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import datetime
import logging
logging.Logger.manager.emittedNoHandlerWarning = 1
import sys
import traceback

from gunicorn import util

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

    def __init__(self, cfg):
        self.error_log = logging.getLogger("gunicorn.error")
        self.access_log = logging.getLogger("gunicorn.access")
        self.error_handlers = []
        self.access_handlers = []

        self.setup(cfg)

    def setup(self, cfg):
        self.cfg = cfg

        loglevel = self.LOG_LEVELS.get(cfg.loglevel.lower(), logging.INFO)
        self.error_log.setLevel(loglevel)
        
        # always info in access log
        self.access_log.setLevel(logging.INFO)

        self._set_handler(self.error_log, cfg.errorlog,
                logging.Formatter(self.error_fmt, self.datefmt))


        if cfg.accesslog is not None:
            self._set_handler(self.access_log, cfg.accesslog,
                fmt=logging.Formatter(self.access_fmt))


    def critical(self, msg, *args, **kwargs):
        self.error_log.exception(msg, *args, **kwargs)

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
        if isinstance(lvl, basestring):
            lvl = self.LOG_LEVELS.get(lvl.lower(), logging.INFO)
        self.error_log.log(lvl, msg, *args, **kwargs)

    def access(self, resp, environ, request_time):
        """ Seee http://httpd.apache.org/docs/2.0/logs.html#combined
        for format details
        """

        if not self.cfg.accesslog:
            return


        status = resp.status.split(None, 1)[0]
        atoms = {
                'h': environ['REMOTE_ADDR'],
                'l': '-',
                'u': '-', # would be cool to get username from basic auth header
                't': self.now(),
                'r': "%s %s %s" % (environ['REQUEST_METHOD'],
                    environ['RAW_URI'], environ["SERVER_PROTOCOL"]),
                's': status,
                'b': str(resp.response_length) or '-',
                'f': environ.get('HTTP_REFERER', '-'),
                'a': environ.get('HTTP_USER_AGENT', '-'),
                'T': str(request_time.seconds),
                'D': str(request_time.microseconds)
                }

        # add WSGI request headers 
        atoms.update(dict([(k,v) for k, v in environ.items() \
                if k.startswith('HTTP_')]))

        for k, v in atoms.items():
            atoms[k] = v.replace('"', '\\"')
    
        try:
            self.access_log.info(self.cfg.access_log_format % atoms)
        except:
            self.error(traceback.format_exc())

    def now(self):
        """ return date in Apache Common Log Format """
        now = datetime.datetime.now()
        month = util.monthname[now.month]
        return '[%02d/%s/%04d:%02d:%02d:%02d]' % (now.day, month,
                now.year, now.hour, now.minute, now.second)


    def reopen_files(self):
        for log in (self.error_log, self.access_log):
            for handler in log.handlers:
                if isinstance(handler, logging.FileHandler):
                    handler.acquire()
                    handler.stream.close()
                    handler.stream = open(handler.baseFilename,
                            handler.mode)
                    handler.release()

    def close_on_exec(self):
        for log in (self.error_log, self.access_log):
            for handler in log.handlers:
                if isinstance(handler, logging.FileHandler):
                    handler.acquire()
                    util.close_on_exec(handler.stream.fileno())
                    handler.release()

   
    def _get_gunicorn_handler(self, log):
        for h in log.handlers:
            if getattr(h, "_gunicorn") == True:
                return h
    
    def _set_handler(self, log, output, fmt):
        # remove previous gunicorn log handler
        h = self._get_gunicorn_handler(log)
        if h:
            log.handlers.remove(h)

        if output == "-":
            h = logging.StreamHandler()
        else:
            h = logging.FileHandler(output)

        h.setFormatter(fmt)
        h._gunicorn = True
        log.addHandler(h)

