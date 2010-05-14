# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import os
import sys

from gunicorn import util

class Application(object):
    """\
    An application interface for configuring and loading
    the various necessities for any given web framework.
    """
    
    def get_config(self):
        return {}
    
    def load(self):
        raise NotImplementedError
        
class WSGIApplication(Application):
    
    def __init__(self, app_uri):
        self.app_uri = app_uri
        
    def load(self):
        return util.import_app(self.app_uri)
        
class DjangoApplication(Application):
    
    def __init__(self, settings_modname, project_path):
        self.project_path = project_path
        self.settings_modname = settings_modname
        
        # update sys.path
        sys.path.insert(0, project_path)
        sys.path.append(os.path.join(project_path, os.pardir))
        
    def load(self):
        import django.core.handlers.wsgi
        os.environ['DJANGO_SETTINGS_MODULE'] = self.settings_modname
        return django.core.handlers.wsgi.WSGIHandler()

class PasterApplication(Application):
    
    def __init__(self, cfgurl, relpath, global_opts):
        self.cfgurl = cfgurl
        self.relpath = relpath
        self.global_opts = global_opts
        
    def local_conf(self):
        from paste.deploy import loadwsgi
        ctx = loadwsgi.loadcontext(loadwsgi.SERVER, self.cfgurl, 
                                        relative_to=self.relpath)

        def mk_bind():
            host = ctx.local_conf.get('host')
            port = ctx.local_conf.get('port')
            if host and port:
                return '%s:%s' % (host, port)
            elif host:
                return host

        ret = {}
        vars = {
            'bind': mk_bind,
            'workers': lambda: ctx.local_conf.get('workers', 1),
            'umask': lambda: int(ctx.local_conf.get('umask', UMASK)),
            'group': lambda: ctx.local_conf.get('group'),
            'user': lambda: ctx.local_conf.get('user')
        }
        for vn in vars:
            if self.global_ops.get(vn):
                val = vars[vn]()
                if val:
                    ret[vn] = val

        keys = ctx.local_conf.items()
        keys = filter(self.global_opts.get, keys)
        keys = filter(ret.has_key, keys)
        ret.update((k, ctx.local_conf[k]) for k in keys)

        if not self.global_opts.get("debug"):
            ret['debug'] = (ctx.global_conf.get('debug') == "true")
            
        ret['default_proc_name'] = ctx.global_conf.get('__file__')
        
        return ret
        
    def load(self):
        from paste.deploy import loadapp
        return loadapp(self.cfgurl, relative_to=self.relpath)
