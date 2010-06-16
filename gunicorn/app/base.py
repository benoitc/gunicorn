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
    LOG_LEVELS = {
        "critical": logging.CRITICAL,
        "error": logging.ERROR,
        "warning": logging.WARNING,
        "info": logging.INFO,
        "debug": logging.DEBUG
    }
    
    def __init__(self, usage=None):
        self.log = logging.getLogger(__name__)
        self.cfg = Config(usage)
        self.callable = None
        self.logger = None
        
        self.cfgparser = self.cfg.parser()
        self.opts, self.args = self.cfgparser.parse_args()

        self.load_config()
  
    def load_config(self):
        cfg = self.init(self.cfgparser, self.opts, self.args)
        
        # Load up the any app specific configuration
        if cfg:
            for k, v in list(cfg.items()):
                self.cfg.set(k.lower(), v)
                
        # Load up the config file if its found.
        if self.opts.config and os.path.exists(self.opts.config):
            cfg = {
                "__builtins__": __builtins__,
                "__name__": "__config__",
                "__file__": self.opts.config,
                "__doc__": None,
                "__package__": None
            }
            try:
                execfile(self.opts.config, cfg, cfg)
            except Exception, e:
                print "Failed to read config file: %s" % self.opts.config
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
        for k, v in list(self.opts.__dict__.items()):
            if v is None:
                continue
            self.cfg.set(k.lower(), v)
               
    def init(self, parser, opts, args):
        raise NotImplementedError
    
    def load(self):
        raise NotImplementedError

    def reload(self):
        self.load_config()
        if self.cfg.spew:
            debug.spew()
        loglevel = self.LOG_LEVELS.get(self.cfg.loglevel.lower(), logging.INFO)
        self.logger.setLevel(loglevel)
        
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
        self.configure_logging()
        Arbiter(self).run()
    
    def configure_logging(self):
        """\
        Set the log level and choose the destination for log output.
        """
        self.logger = logging.getLogger('gunicorn')

        handlers = []
        if self.cfg.logfile != "-":
            handlers.append(logging.FileHandler(self.cfg.logfile))
        else:
            handlers.append(logging.StreamHandler())

        loglevel = self.LOG_LEVELS.get(self.cfg.loglevel.lower(), logging.INFO)
        self.logger.setLevel(loglevel)
        
        format = r"%(asctime)s [%(process)d] [%(levelname)s] %(message)s"
        datefmt = r"%Y-%m-%d %H:%M:%S"
        for h in handlers:
            h.setFormatter(logging.Formatter(format, datefmt))
            self.logger.addHandler(h)


