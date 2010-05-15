# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import ConfigParser
import grp
import inspect
import optparse
import os
import pwd
import sys
import types

from gunicorn import __version__
from gunicorn import util

class Setting(object):
    def __init__(self, name, opts):
        self.name = name
        self.section = opts["section"]
        self.order = int(opts.get("order", 0))
        self.cli = opts["cli"].split()
        self.type = opts["type"].strip()
        self.arity = opts.get('arity', None)
        if self.arity:
            self.arity = int(self.arity)
        self.meta = opts.get('meta', "").strip() or None
        self.action = opts.get('action', "store").strip()
        self.default = opts.get('default').strip() or None
        self.desc = opts["desc"]
        self.short = self.desc.splitlines()[0].strip()

        # Special case the callable types.
        self.value = None
        if self.default and self.type != 'callable':
            self.set(self.default, modified=False)

        # A flag that tells us if this setting
        # has been altered
        self.modified = False
    
    def add_option(self, parser):
        if not len(self.cli):
            return
        args = tuple(self.cli)
        opttypes = {
            "pos_int": "int",
            "bool": None
        }
        kwargs = {
            "dest": self.name,
            "metavar": self.meta or None,
            "action": self.action,
            "type": opttypes.get(self.type, "string"),
            "default": None,
            "help": "%s [%s]" % (self.short, self.default)
        }
        parser.add_option(*args, **kwargs)
    
    def get(self):
        return self.value
    
    def set(self, val, modified=True):
        validator = getattr(self, "set_%s" % self.type)
        self.value = validator(val)
        self.modified = modified
    
    def set_bool(self, val):
        if isinstance(val, types.BooleanType):
            return val
        if val.lower().strip() == "true":
            return True
        elif val.lower().strip() == "false":
            return False
        else:
            raise ValueError("Invalid boolean: %s" % val)
    
    def set_pos_int(self, val):
        if not isinstance(val, (types.IntType, types.LongType)):
            val = int(val, 0)
        if val < 0:
            raise ValueError("Value must be positive: %s" % val)
        return val

    def set_string(self, val):
        return val.strip()
    
    def set_callable(self, val):
        if not callable(val):
            raise TypeError("Value is not callable: %s" % val)
        arity = len(inspect.getargspec(val)[0])
        if arity != self.arity:
            raise TypeError("Value must have an arity of: %s" % self.arity)
        return val

class Config(object):
        
    def __init__(self, usage):
        self.settings = {}
        self.usage = usage

        path = os.path.join(os.path.dirname(__file__), "options.ini")
        opts = ConfigParser.SafeConfigParser()
        if not len(opts.read(path)):
            raise RuntimeError("Options configuration file is missing!")
        
        for sect in opts.sections():
            self.settings[sect] = Setting(sect, dict(opts.items(sect)))

        # Special case hook functions
        self.settings['pre_fork'].set(def_pre_fork, modified=False)
        self.settings['post_fork'].set(def_post_fork, modified=False)
        self.settings['pre_exec'].set(def_pre_exec, modified=False)
        
    def __getattr__(self, name):
        if name not in self.settings:
            raise AttributeError("No configuration setting for: %s" % name)
        return self.settings[name].get()
    
    def __setattr__(self, name, value):
        if name != "settings" and name in self.settings:
            raise AttributeError("Invalid access!")
        super(Config, self).__setattr__(name, value)
    
    def set(self, name, value):
        if name not in self.settings:
            raise AttributeError("No configuration setting for: %s" % name)
        self.settings[name].set(value)

    def parser(self):
        kwargs = {
            "usage": self.usage,
            "version": __version__,
            "formatter": HelpFormatter()
        }
        parser = optparse.OptionParser(**kwargs)

        keys = self.settings.keys()
        def sorter(k):
            return (self.settings[k].section, self.settings[k].order)
        keys.sort(key=sorter)
        for k in keys:
            self.settings[k].add_option(parser)
        return parser

    def was_modified(self, name):
        return self.settings[name].modified

    @property
    def worker_class(self):
        uri = self.settings['worker_class'].get()
        worker_class = util.load_worker_class(uri)
        if hasattr(worker_class, "setup"):
            worker_class.setup()
        return worker_class

    @property   
    def workers(self):
        if self.settings['debug'].get():
            return 1
        return self.settings['workers'].get()

    @property
    def address(self):
        bind = self.settings['bind'].get()
        return util.parse_address(util.to_bytestring(bind))
        
    @property
    def uid(self):
        user = self.settings['user'].get()
        
        if not user:
            return os.geteuid()
        elif user.isdigit() or isinstance(user, int):
            return int(user)
        else:
            return pwd.getpwnam(user).pw_uid
        
    @property
    def gid(self):
        group = self.settings['group'].get()

        if not group:
            return os.getegid()
        elif group.isdigit() or isinstance(user, int):
            return int(group)
        else:
            return grp.getgrnam(group).gr_gid
        
    @property
    def proc_name(self):
        pn = self.settings['proc_name'].get()
        if pn:
            return pn
        else:
            return self.settings['default_proc_name']

    @property
    def pre_fork(self):
        return self.settings['pre_fork'].get()
    
    @property
    def post_fork(self):
        return self.settings['post_fork'].get()
    
    @property
    def pre_exec(self):
        return self.settings['pre_exec'].get()


def def_pre_fork(server, worker):
    pass

def def_post_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)" % worker.pid)

def def_pre_exec(server):
    server.log.info("Forked child, reexecuting.")


class HelpFormatter(optparse.IndentedHelpFormatter):
    pass


