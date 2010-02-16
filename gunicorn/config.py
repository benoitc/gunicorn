# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import os
import sys

from gunicorn import util

class Config(object):
    
    DEFAULTS = dict(
        bind='127.0.0.1:8000',
        daemon=False,
        debug=False,
        logfile='-',
        loglevel='info',
        pidfile=None,
        workers=1,
        umask=0,
        user=None,
        group=None,
        
        after_fork=lambda server, worker: server.log.info(
                        "worker=%s spawned pid=%s" % (worker.id, str(worker.pid))),
        
        before_fork=lambda server, worker: server.log.info(
                        "worker=%s spawning" % worker.id),
                        
        before_exec=lambda server: server.log.info("forked child, reexecuting")
    )
    
    def __init__(self, cmdopts, path=None):
        if not path:
            self.config_file = os.path.join(os.getcwd(), 'gunicorn.conf.py')
        else:
            self.config_file =  os.path.abspath(os.path.normpath(path))
        self.cmdopts = cmdopts    
        self.conf = {}
        self.load()
            
    def _load_file(self):
        """
        Returns a dict of stuff found in the config file.
        Defaults to $PWD/guniconf.py.
        """
        if not os.path.exists(self.config_file):
            return {}

        config = {}
        try:
            execfile(self.config_file, config)
        except:
            sys.exit("Could not read config file %r" % (self.config_file,))

        config.pop("__builtins__", None)
        return config
        
    def load(self):
        self.conf = self.DEFAULTS.copy()
        self.conf.update(self._load_file())
        for key, value in list(self.cmdopts.items()):
            if value and value is not None:
                print "%s = %s" % (key, value)
                self.conf[key] = value
           
    def __getitem__(self, key):
        try:
            return getattr(self, key)
        except AttributeError:
            pass
        return self.conf[key]
        
    def __getattr__(self, key):
        try:
            getattr(super(Config, self), key)
        except AttributeError:
            if key in self.conf:
                return self.conf[key]
            raise
            
    def __contains__(self, key):
        return (key in self.conf)
        
    def __iter__(self):
        return self.conf.iteritems()
     
    @property   
    def workers(self):
        if not self.conf.get('workers'):
            raise RuntimeError("invalid workers number")
        workers = int(self.conf["workers"])
        if not workers:
            raise RuntimeError("number of workers < 1")
        if self.conf['debug'] == True:
            workers = 1
        return workers
        
    @property
    def address(self):
        if not self.conf['bind']:
            raise RuntimeError("Listener address is not set")   
        return util.parse_address(self.conf['bind'])
        
    def after_fork(self, *args):
        after_fork = self.conf.get("after_fork")
        if not after_fork: return
        if not callable(after_fork):
            raise RuntimeError("after_fork hook isn't a callable")
        return after_fork(*args)
        
    def before_fork(self, *args):
        before_fork = self.conf.get("before_fork")
        if not before_fork: return
        if not callable(before_fork):
            raise RuntimeError("before_fork hook isn't a callable")
        return before_fork(*args)
        
    def before_exec(self, *args):
        before_exec = self.conf.get("before_exec")
        if not before_exec: return
        if not callable(before_exec):
            raise RuntimeError("before_exec hook isn't a callable")
        return before_exec(*args)
        
        
            
    
        
        
    
        