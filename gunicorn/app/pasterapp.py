# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import os
import pkg_resources
import sys

try:
    import configparser as ConfigParser
except ImportError:
    import ConfigParser

from paste.deploy import loadapp, loadwsgi
SERVER = loadwsgi.SERVER

from gunicorn.app.base import Application
from gunicorn.config import Config


class PasterBaseApplication(Application):

    def app_config(self):
        cx = loadwsgi.loadcontext(SERVER, self.cfgurl, relative_to=self.relpath)
        gc, lc = cx.global_conf.copy(), cx.local_conf.copy()
        cfg = {}

        host, port = lc.pop('host', ''), lc.pop('port', '')
        if host and port:
            cfg['bind'] = '%s:%s' % (host, port)
        elif host:
            cfg['bind'] = host.split(',')

        cfg['workers'] = int(lc.get('workers', 1))
        cfg['umask'] = int(lc.get('umask', 0))
        cfg['default_proc_name'] = gc.get('__file__')

        for k, v in gc.items():
            if k not in self.cfg.settings:
                continue
            cfg[k] = v

        for k, v in lc.items():
            if k not in self.cfg.settings:
                continue
            cfg[k] = v

        return cfg

    def load_config(self):
        super(PasterBaseApplication, self).load_config()

        # reload logging conf
        if hasattr(self, "cfgfname"):
            parser = ConfigParser.ConfigParser()
            parser.read([self.cfgfname])
            if parser.has_section('loggers'):
                from logging.config import fileConfig
                config_file = os.path.abspath(self.cfgfname)
                fileConfig(config_file, dict(__file__=config_file,
                                             here=os.path.dirname(config_file)))


class PasterApplication(PasterBaseApplication):

    def init(self, parser, opts, args):
        if len(args) != 1:
            parser.error("No application name specified.")

        cfgfname = os.path.normpath(os.path.join(os.getcwd(), args[0]))
        cfgfname = os.path.abspath(cfgfname)
        if not os.path.exists(cfgfname):
            parser.error("Config file not found: %s" % cfgfname)

        self.cfgurl = 'config:%s' % cfgfname
        self.relpath = os.path.dirname(cfgfname)
        self.cfgfname = cfgfname

        sys.path.insert(0, self.relpath)
        pkg_resources.working_set.add_entry(self.relpath)

        return self.app_config()

    def load(self):
        return loadapp(self.cfgurl, relative_to=self.relpath)


class PasterServerApplication(PasterBaseApplication):

    def __init__(self, app, gcfg=None, host="127.0.0.1", port=None, *args, **kwargs):
        self.cfg = Config()
        self.app = app
        self.callable = None

        gcfg = gcfg or {}
        cfgfname = gcfg.get("__file__")
        if cfgfname is not None:
            self.cfgurl = 'config:%s' % cfgfname
            self.relpath = os.path.dirname(cfgfname)
            self.cfgfname = cfgfname

        cfg = kwargs.copy()

        if port and not host.startswith("unix:"):
            bind = "%s:%s" % (host, port)
        else:
            bind = host
        cfg["bind"] = bind.split(',')

        if gcfg:
            for k, v in gcfg.items():
                cfg[k] = v
            cfg["default_proc_name"] = cfg['__file__']

        try:
            for k, v in cfg.items():
                if k.lower() in self.cfg.settings and v is not None:
                    self.cfg.set(k.lower(), v)
        except Exception as e:
            sys.stderr.write("\nConfig error: %s\n" % str(e))
            sys.stderr.flush()
            sys.exit(1)

    def load_config(self):
        if not hasattr(self, "cfgfname"):
            return

        cfg = self.app_config()
        for k, v in cfg.items():
            try:
                self.cfg.set(k.lower(), v)
            except:
                sys.stderr.write("Invalid value for %s: %s\n\n" % (k, v))
                raise

    def load(self):
        if hasattr(self, "cfgfname"):
            return loadapp(self.cfgurl, relative_to=self.relpath)

        return self.app


def run():
    """\
    The ``gunicorn_paster`` command for launcing Paster compatible
    apllications like Pylons or Turbogears2
    """
    from gunicorn.app.pasterapp import PasterApplication
    PasterApplication("%(prog)s [OPTIONS] pasteconfig.ini").run()


def paste_server(app, gcfg=None, host="127.0.0.1", port=None, *args, **kwargs):
    """\
    A paster server.

    Then entry point in your paster ini file should looks like this:

    [server:main]
    use = egg:gunicorn#main
    host = 127.0.0.1
    port = 5000

    """
    from gunicorn.app.pasterapp import PasterServerApplication
    PasterServerApplication(app, gcfg=gcfg, host=host, port=port, *args, **kwargs).run()
