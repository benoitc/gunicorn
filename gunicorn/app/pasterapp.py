# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import os
import pkg_resources
import sys

from paste.deploy import loadapp, loadwsgi
SERVER = loadwsgi.SERVER

from gunicorn.app.base import Application
from gunicorn.config import Config

class PasterApplication(Application):
    
    def init(self, parser, opts, args):
        if len(args) != 1:
            parser.error("No application name specified.")

        cfgfname = os.path.normpath(os.path.join(os.getcwd(), args[0]))
        cfgfname = os.path.abspath(cfgfname)
        if not os.path.exists(cfgfname):
            parser.error("Config file not found.")

        self.cfgurl = 'config:%s' % cfgfname
        self.relpath = os.path.dirname(cfgfname)

        sys.path.insert(0, self.relpath)
        pkg_resources.working_set.add_entry(self.relpath)
        
        return self.app_config()

    def app_config(self):
        cx = loadwsgi.loadcontext(SERVER, self.cfgurl, relative_to=self.relpath)
        gc, lc = cx.global_conf.copy(), cx.local_conf.copy()

        cfg = {}
        
        host, port = lc.pop('host', ''), lc.pop('port', '')
        if host and port:
            cfg['bind'] = '%s:%s' % (host, port)
        elif host:
            cfg['bind'] = host

        cfg['workers'] = int(lc.get('workers', 1))
        cfg['umask'] = int(lc.get('umask', 0))
        cfg['default_proc_name'] = gc.get('__file__')
        
        for k, v in lc.items():
            if k not in self.cfg.settings:
                continue
            cfg[k] = v

        return cfg
        
    def load(self):
        return loadapp(self.cfgurl, relative_to=self.relpath)

class PasterServerApplication(Application):
    
    def __init__(self, app, gcfg=None, host="127.0.0.1", port=None, *args, **kwargs):
        self.cfg = Config()
        self.app = app
        self.callable = None

        cfg = kwargs.copy()

        if port and not host.startswith("unix:"):
            bind = "%s:%s" % (host, port)
        else:
            bind = host
        cfg["bind"] = bind

        if gcfg:
            for k, v in list(gcfg.items()):
                cfg[k] = v
            cfg["default_proc_name"] = cfg['__file__']

        for k, v in list(cfg.items()):
            if k.lower() in self.cfg.settings and v is not None:
                self.cfg.set(k.lower(), v)
            
        self.configure_logging()

    def load(self):
        return self.app


