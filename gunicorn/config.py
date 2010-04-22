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
        spew=False,
        timeout=30,
        tmp_upload_dir=None,
        umask="0",
        user=None,
        workers=1,
        worker_connections=1000,
        worker_class="egg:gunicorn#sync",
        
        after_fork=lambda server, worker: server.log.info(
            "Worker spawned (pid: %s)" % worker.pid),
        
        before_fork=lambda server, worker: True,

        before_exec=lambda server: server.log.info("Forked child, reexecuting")
    )
    
    def __init__(self, opts, path=None):
        self.cfg = self.DEFAULTS.copy()

        if path is None:
            path = os.path.join(os.getcwd(), self.DEFAULT_CONFIG_FILE)
        if os.path.exists(path):
            try:
                execfile(path, globals(), self.cfg)
            except Exception, e:
                sys.exit("Could not read config file: %r\n    %s" % (path, e))
            self.cfg.pop("__builtins__")

        opts = [(k, v) for (k, v) in opts.iteritems() if v is not None]
        self.cfg.update(dict(opts))
           
    def __getitem__(self, key):
        try:
            return getattr(self, key)
        except AttributeError:
            pass
        return self.cfg[key]
        
    def __getattr__(self, key):
        try:
            super(Config, self).__getattribute__(key)
        except AttributeError:
            if key in self.cfg:
                return self.cfg[key]
            raise
            
    def __contains__(self, key):
        return (key in self.cfg)
        
    def __iter__(self):
        return self.cfg.iteritems()

    def get(self, key, default=None):
        return self.cfg.get(key, default)

    @property
    def worker_class(self):
        uri = self.cfg.get('worker_class', None) or 'egg:gunicorn#sync'
        worker_class = util.load_worker_class(uri)
        if hasattr(worker_class, "setup"):
            worker_class.setup()
        return worker_class

    @property   
    def workers(self):
        if not self.cfg.get('workers'):
            raise RuntimeError("invalid workers number")
        workers = int(self.cfg["workers"])
        if not workers:
            raise RuntimeError("number of workers < 1")
        if self.cfg['debug'] == True: 
            workers = 1
        return workers

    @property
    def address(self):
        if not self.cfg['bind']:
            raise RuntimeError("Listener address is not set")
        return util.parse_address(util.to_bytestring(self.cfg['bind']))
        
    @property
    def umask(self):
        if not self.cfg.get('umask'):
            return 0
        umask = self.cfg['umask']
        if isinstance(umask, basestring):
            return int(umask, 0)
        return umask
        
    @property
    def uid(self):
        if not self.cfg.get('user'):
            return os.geteuid()
        
        user =  self.cfg.get('user')
        if user.isdigit() or isinstance(user, int):
            uid = int(user)
        else:
            uid = pwd.getpwnam(user).pw_uid
        return uid
        
    @property
    def gid(self):
        if not self.cfg.get('group'):
            return os.getegid()
        group = self.cfg.get('group')
        if group.isdigit() or isinstance(group, int):
            gid = int(group)
        else:
            gid = grp.getgrnam(group).gr_gid
        return gid
        
    @property
    def proc_name(self):
        if not self.cfg.get('proc_name'):
            return self.cfg.get('default_proc_name')
        return self.cfg.get('proc_name')
        
    def after_fork(self, *args):
        return self._hook("after_fork", *args)
        
    def before_fork(self, *args):
        return self._hook("before_fork", *args)
        
    def before_exec(self, *args):
        return self._hook("before_exec", *args)

    def _hook(self, hookname, *args):
        hook = self.cfg.get(hookname)
        if not hook:
            return
        if not callable(hook):
            raise RuntimeError("%r hook isn't a callable" % hookname)
        return hook(*args)
