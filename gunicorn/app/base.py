# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import logging
import os
import sys
import traceback

from gunicorn import util
from gunicorn.arbiter import Arbiter
from gunicorn.config import Config
from gunicorn import debug

class Application(object):
    """\
    An application interface for configuring and loading
    the various necessities for any given web framework.
    """
    def __init__(self, usage=None):
        self.log = logging.getLogger(__name__)
        self.cfg = Config(usage)
        self.callable = None
        
        parser = self.cfg.parser()
        opts, args = parser.parse_args()
        cfg = self.init(parser, opts, args)
        
        # Load up the any app specific configuration
        if cfg:
            for k, v in list(cfg.items()):
                self.cfg.set(k.lower(), v)
        
        # Load up the config file if its found.
        if opts.config and os.path.exists(opts.config):
            cfg = {
                "__builtins__": __builtins__,
                "__name__": "__config__",
                "__file__": opts.config,
                "__doc__": None,
                "__package__": None
            }
            try:
                execfile(opts.config, cfg, cfg)
            except Exception, e:
                print "Failed to read config file: %s" % opts.config
                traceback.print_exc()
                sys.exit(1)
        
            for k, v in list(cfg.items()):
                # Ignore unknown names
                if k not in self.cfg.settings:
                    continue
                try:
                    self.cfg.set(k.lower(), v)
                except:
                    sys.stderr.write("Invalid value for %s: %s\n\n" % (k, v))
                    raise
            
        # Lastly, update the configuration with any command line
        # settings.
        for k, v in list(opts.__dict__.items()):
            if v is None:
                continue
            self.cfg.set(k.lower(), v)
            
        self.configure_logging()
    
    def init(self, parser, opts, args):
        raise NotImplementedError
    
    def load(self):
        raise NotImplementedError
        
    def wsgi(self):
        if self.callable is None:
            self.callable = self.load()
        return self.callable
    
    def run(self):
        if self.cfg.spew:
            debug.spew()
        if self.cfg.daemon:
            util.daemonize()
        else:
            os.setpgrp()
        Arbiter(self).run()
    
    def configure_logging(self):
        """\
        Set the log level and choose the destination for log output.
        """
        logger = logging.getLogger('gunicorn')

        handlers = []
        if self.cfg.logfile != "-":
            handlers.append(logging.FileHandler(self.cfg.logfile))
        else:
            handlers.append(logging.StreamHandler())

        levels = {
            "critical": logging.CRITICAL,
            "error": logging.ERROR,
            "warning": logging.WARNING,
            "info": logging.INFO,
            "debug": logging.DEBUG
        }

        loglevel = levels.get(self.cfg.loglevel.lower(), logging.INFO)
        logger.setLevel(loglevel)
        
        format = r"%(asctime)s [%(process)d] [%(levelname)s] %(message)s"
        datefmt = r"%Y-%m-%d %H:%M:%S"
        for h in handlers:
            h.setFormatter(logging.Formatter(format, datefmt))
            logger.addHandler(h)


