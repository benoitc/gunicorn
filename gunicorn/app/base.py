# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import os
import sys
import traceback

from gunicorn import util
from gunicorn.arbiter import Arbiter
from gunicorn.config import Config
from gunicorn import debug
from gunicorn.six import execfile_


class Application(object):
    """\
    An application interface for configuring and loading
    the various necessities for any given web framework.
    """

    def __init__(self, usage=None, prog=None):
        self.usage = usage
        self.cfg = None
        self.callable = None
        self.prog = prog
        self.logger = None
        self.do_load_config()

    def do_load_config(self):
        try:
            self.load_config()
        except Exception as e:
            sys.stderr.write("\nError: %s\n" % str(e))
            sys.stderr.flush()
            sys.exit(1)

    def load_config(self):
        # init configuration
        self.cfg = Config(self.usage, prog=self.prog)

        # parse console args
        parser = self.cfg.parser()
        args = parser.parse_args()

        # optional settings from apps
        cfg = self.init(parser, args, args.args)

        # Load up the any app specific configuration
        if cfg and cfg is not None:
            for k, v in cfg.items():
                self.cfg.set(k.lower(), v)

        # Load up the config file if its found.
        if args.config and os.path.exists(args.config):
            cfg = {
                "__builtins__": __builtins__,
                "__name__": "__config__",
                "__file__": args.config,
                "__doc__": None,
                "__package__": None
            }
            try:
                execfile_(args.config, cfg, cfg)
            except Exception:
                print("Failed to read config file: %s" % args.config)
                traceback.print_exc()
                sys.exit(1)

            for k, v in cfg.items():
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
        for k, v in args.__dict__.items():
            if v is None:
                continue
            if k == "args":
                continue
            self.cfg.set(k.lower(), v)

    def init(self, parser, opts, args):
        raise NotImplementedError

    def load(self):
        raise NotImplementedError

    def reload(self):
        self.do_load_config()
        if self.cfg.spew:
            debug.spew()

    def wsgi(self):
        if self.callable is None:
            self.callable = self.load()
        return self.callable

    def run(self):
        if self.cfg.check_config:
            try:
                self.load()
            except:
                sys.stderr.write("\nError while loading the application:\n\n")
                traceback.print_exc()
                sys.stderr.flush()
                sys.exit(1)
            sys.exit(0)

        if self.cfg.spew:
            debug.spew()
        if self.cfg.daemon:
            util.daemonize()

        # set python paths
        if self.cfg.pythonpath and self.cfg.pythonpath is not None:
            paths = self.cfg.pythonpath.split(",")
            for path in paths:
                pythonpath = os.path.abspath(self.cfg.pythonpath)
                if pythonpath not in sys.path:
                    sys.path.insert(0, pythonpath)

        try:
            Arbiter(self).run()
        except RuntimeError as e:
            sys.stderr.write("\nError: %s\n\n" % e)
            sys.stderr.flush()
            sys.exit(1)
