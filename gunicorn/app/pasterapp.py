# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import os
import pkg_resources
import sys

from paste.deploy import loadapp, loadwsgi
SERVER = loadwsgi.SERVER

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
        gc, lc = cx.global_conf, cx.local_conf

        cfg = {}
        
        host, port = lc.get('host'), lc.get('port')
        if host and port:
            cfg['bind'] = '%s:%s' % (host, port)
        elif host:
            cfg['bind'] = host

        cfg['workers'] = int(lc.get('workers', 1))
        cfg['umask'] = int(lc.get('umask', 0))
        cfg['default_proc_name'] = gc.get('__file__')
        cfg.update(dict((k,v) for (k,v) in lc.items() if k not in cfg))
        return cfg
        
    def load(self):
        return loadapp(self.cfgurl, relative_to=self.relpath)

class PasterServerApplication(Application):
    
    def __init__(self, app, *args, **kwargs):
        self.log = logging.getLogger(__name__)
        self.cfg = Config()
        self.app = app

        cfg = {}
        host, port = kwargs.get('host'), kwargs.get('port')
        if host and port:
            cfg['bind'] = '%s:%s' % (host, port)
        elif host:
            cfg['bind'] = host

        if gcfg:
            for k, v in list(gcfg.items()):
                if k.lower() in self.cfg.settings:
                    self.cfg.set(k.lower(), v)
            self.cfg.default_proc_name = kwargs.__file__

        self.configure_logging(cfg)

    def load(self):
        return self.app


