# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import grp
import os
import pwd
import sys

from gunicorn import util

class Config(object):
    
    DEFAULT_CONFIG_FILE = 'gunicorn.conf.py'
    
    DEFAULTS = dict(
        arbiter="egg:gunicorn",
        backlog=2048,
        bind='127.0.0.1:8000',
        daemon=False,
        debug=False,
        default_proc_name = os.getcwd(),
        group=None,
        keepalive=2,
        logfile='-',
        loglevel='info',
        pidfile=None,
        proc_name = None,
        timeout=30,
        tmp_upload_dir=None,
        umask="0",
        user=None,
        workers=1,
        worker_connections=1000,
        
        after_fork=lambda server, worker: server.log.info(
            "Worker spawned (pid: %s)" % worker.pid),
        
        before_fork=lambda server, worker: True,

        before_exec=lambda server: server.log.info("Forked child, reexecuting")
    )
    
    def __init__(self, cmdopts, path=None):
        if not path:
            self.config_file = os.path.join(os.getcwd(), 
                                    self.DEFAULT_CONFIG_FILE)
        else:
            self.config_file =  os.path.abspath(os.path.normpath(path))
        self.cmdopts = cmdopts    
        self.conf = {}
        self.load()
            
    def _load_file(self):
        """
        Returns a dict of stuff found in the config file.
        Defaults to $PWD/gunicorn.conf.py.
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
    def arbiter(self):
        uri = self.conf.get('arbiter', 'egg:gunicorn')
        arbiter = util.parse_arbiter_uri(uri)
        if hasattr(arbiter, 'setup'):
            arbiter.setup()
        return arbiter

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
        return util.parse_address(util.to_bytestring(self.conf['bind']))
        
    @property
    def umask(self):
        if not self.conf.get('umask'):
            return 0
        umask = self.conf['umask']
        if isinstance(umask, basestring):
            return int(umask, 0)
        return umask
        
    @property
    def uid(self):
        if not self.conf.get('user'):
            return os.geteuid()
        
        user =  self.conf.get('user')
        if user.isdigit() or isinstance(user, int):
            uid = int(user)
        else:
            uid = pwd.getpwnam(user).pw_uid
        return uid
        
    @property
    def gid(self):
        if not self.conf.get('group'):
            return os.getegid()
        group = self.conf.get('group')
        if group.isdigit() or isinstance(group, int):
            gid = int(group)
        else:
            gid = grp.getgrnam(group).gr_gid
        
        return gid
        
    @property
    def proc_name(self):
        if not self.conf.get('proc_name'):
            return self.conf.get('default_proc_name')
        return self.conf.get('proc_name')
        
    def _hook(self, hookname, *args):
        hook = self.conf.get(hookname)
        if not hook: return
        if not callable(hook):
            raise RuntimeError("%s hook isn't a callable" % hookname)
        return hook(*args)
        
    def after_fork(self, *args):
        return self._hook("after_fork", *args)
        
    def before_fork(self, *args):
        return self._hook("before_fork", *args)
        
    def before_exec(self, *args):
        return self._hook("before_exec", *args)
                  
