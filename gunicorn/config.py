# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from __future__ import with_statement

import copy
import grp
import inspect
import optparse
import os
import pwd
import textwrap
import types

from gunicorn import __version__
from gunicorn import util

KNOWN_SETTINGS = []

class Config(object):
        
    def __init__(self, usage=None):
        self.settings = dict((s.name, s.copy()) for s in KNOWN_SETTINGS)
        self.usage = usage
        
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
            "version": __version__
        }
        parser = optparse.OptionParser(**kwargs)

        keys = self.settings.keys()
        def sorter(k):
            return (self.settings[k].section, self.settings[k].order)
        keys.sort(key=sorter)
        for k in keys:
            self.settings[k].add_option(parser)
        return parser

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
        elif group.isdigit() or isinstance(group, int):
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

class Setting(object):
    def __init__(self, name):
        self.name = name
        self.value = None
        self.section = None
        self.order = len(KNOWN_SETTINGS)
        self.cli = None
        self.validator = None
        self.type = None
        self.meta = None
        self.action = None
        self.default = None
        self.short = None
        self.desc = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, traceback):
        if exc_type is None:
            KNOWN_SETTINGS.append(self)
            if self.default is not None:
                self.set(self.default)
    
    def fmt_desc(self, desc):
        desc = textwrap.dedent(desc).strip()
        self.desc = desc
        self.short = desc.splitlines()[0]
        
    def add_option(self, parser):
        if not self.cli:
            return
        args = tuple(self.cli)
        kwargs = {
            "dest": self.name,
            "metavar": self.meta or None,
            "action": self.action or "store",
            "type": self.type or "string",
            "default": None,
            "help": "%s [%s]" % (self.short, self.default)
        }
        if kwargs["action"] != "store":
            kwargs.pop("type")
        parser.add_option(*args, **kwargs)
    
    def copy(self):
        return copy.copy(self)
    
    def get(self):
        return self.value
    
    def set(self, val):
        assert callable(self.validator), "Invalid validator: %s" % self.name
        self.value = self.validator(val)

def validate_bool(val):
    if isinstance(val, types.BooleanType):
        return val
    if not isinstance(val, basestring):
        raise TypeError("Invalid type for casting: %s" % val)
    if val.lower().strip() == "true":
        return True
    elif val.lower().strip() == "false":
        return False
    else:
        raise ValueError("Invalid boolean: %s" % val)

def validate_pos_int(val):
    if not isinstance(val, (types.IntType, types.LongType)):
        val = int(val, 0)
    else:
        # Booleans are ints!
        val = int(val)
    #print "Setting: %s" % val
    if val < 0:
        raise ValueError("Value must be positive: %s" % val)
    return val

def validate_string(val):
    if val is None:
        return None
    if not isinstance(val, basestring):
        raise TypeError("Not a string: %s" % val)
    return val.strip()

def validate_callable(arity):
    def _validate_callable(val):
        if not callable(val):
            raise TypeError("Value is not callable: %s" % val)
        if arity != len(inspect.getargspec(val)[0]):
            raise TypeError("Value must have an arity of: %s" % arity)
        return val
    return _validate_callable

with Setting("config") as s:
    s.section = "Config"
    s.cli = ["-c", "--config"]
    s.meta = "FILE"
    s.validator = validate_string
    s.default = None
    s.fmt_desc("""\
        The path to a Gunicorn config file.
        
        By default Gunicorn will try to read a file named 'gunicorn.conf.py' in
        the current directory.
        
        Only has an effect when specified on the command line or as part of an
        application specific configuration.    
        """)

with Setting("bind") as s:
    s.section = "Server Socket"
    s.cli = ["-b", "--bind"]
    s.meta = "ADDRESS"
    s.validator = validate_string
    s.default = "127.0.0.1:8000"
    s.fmt_desc("""\
        The socket to bind.
        
        A string of the form: 'HOST', 'HOST:PORT', 'unix:PATH'. An IP is a valid
        HOST.
        """)

with Setting("backlog") as s:
    s.section = "Server Socket"
    s.cli = ["--backlog"]
    s.meta = "INT"
    s.validator = validate_pos_int
    s.type = "int"
    s.default = 2048
    s.fmt_desc("""\
        The maximum number of pending connections.    
        
        This refers to the number of clients that can be waiting to be served.
        Exceeding this number results in the client getting an error when
        attempting to connect. It should only affect servers under significant
        load.
        
        Must be a positive integer. Generally set in the 64-2048 range.    
        """)

with Setting("workers") as s:
    s.section = "Worker Processes"
    s.cli = ["-w", "--workers"]
    s.meta = "INT"
    s.validator = validate_pos_int
    s.type = "int"
    s.default = 1
    s.fmt_desc("""\
        The number of worker process for handling requests.
        
        A positive integer generally in the 2-4 x $(NUM_CORES) range. You'll
        want to vary this a bit to find the best for your particular
        application's work load.
        """)

with Setting("worker_class") as s:
    s.section = "Worker Processes"
    s.cli = ["-k", "--worker-class"]
    s.meta = "STRING"
    s.validator = validate_string
    s.default = "egg:gunicorn#sync"
    s.fmt_desc("""\
        The type of workers to use.
        
        The default async class should handle most 'normal' types of work loads.
        You'll want to read http://gunicorn/deployment.hml for information on
        when you might want to choose one of the other worker classes.
        
        An string referring to a 'gunicorn.workers' entry point or a
        MODULE:CLASS pair where CLASS is a subclass of
        gunicorn.workers.base.Worker.
        
        The default provided values are:
        
        * egg:gunicorn#sync
        * egg:gunicorn#eventlet - Requires eventlet >= 0.9.7
        * egg:gunicorn#gevent   - Requires gevent >= 0.12.2 (?)
        * egg:gunicorn#tornado  - Requires tornado >= 0.2    
        """)

with Setting("worker_connections") as s:
    s.section = "Worker Processes"
    s.cli = ["--worker-connections"]
    s.meta = "INT"
    s.validator = validate_pos_int
    s.type = "int"
    s.default = 1000
    s.fmt_desc("""\
        The maximum number of simultaneous clients.
        
        This setting only affects the Eventlet and Gevent worker types.
        """)

with Setting("timeout") as s:
    s.section = "Worker Processes"
    s.cli = ["-t", "--timeout"]
    s.meta = "INT"
    s.validator = validate_pos_int
    s.type = "int"
    s.default = 30
    s.fmt_desc("""\
        Workers silent for more than this many seconds are killed and restarted.
        
        Generally set to thirty seconds. Only set this noticeably higher if
        you're sure of the repercussions for sync workers. For the non sync
        workers it just means that the worker process is still communicating and
        is not tied to the length of time required to handle a single request.
        """)

with Setting("keepalive") as s:
    s.section = "Worker Processes"
    s.cli = ["--keep-alive"]
    s.meta = "INT"
    s.validator = validate_pos_int
    s.type = "int"
    s.default = 2
    s.fmt_desc("""\
        The number of seconds to wait for requests on a Keep-Alive connection.
        
        Generally set in the 1-5 seconds range.    
        """)

with Setting("debug") as s:
    s.section = "Debugging"
    s.cli = ["--debug"]
    s.validator = validate_bool
    s.action = "store_true"
    s.default = False
    s.fmt_desc("""\
        Turn on debugging in the server.
        
        This limits the number of worker processes to 1 and changes some error
        handling that's sent to clients.
        """)

with Setting("spew") as s:
    s.section = "Debugging"
    s.cli = ["--spew"]
    s.validator = validate_bool
    s.action = "store_true"
    s.default = False
    s.fmt_desc("""\
        Install a trace function that spews every line executed by the server.
        
        This is the nuclear option.    
        """)

with Setting("preload_app") as s:
    s.section = "Server Mechanics"
    s.cli = ["--preload"]
    s.validator = validate_bool
    s.action = "store_true"
    s.default = False
    s.fmt_desc("""\
        Load application code before the worker processes are forked.
        
        By preloading an application you can save some RAM resources as well as
        speed up server boot times. Although, if you defer application loading
        to each worker process, you can reload your application code easily by
        restarting workers.
        """)

with Setting("daemon") as s:
    s.section = "Server Mechanics"
    s.cli = ["-D", "--daemon"]
    s.validator = validate_bool
    s.action = "store_true"
    s.default = False
    s.fmt_desc("""\
        Daemonize the Gunicorn process.
        
        Detaches the server from the controlling terminal and enters the
        background.
        """)

with Setting("pidfile") as s:
    s.section = "Server Mechanics"
    s.cli = ["-p", "--pid"]
    s.meta = "FILE"
    s.validator = validate_string
    s.default = None
    s.fmt_desc("""\
        A filename to use for the PID file.
        
        If not set, no PID file will be written.
        """)

with Setting("user") as s:
    s.section = "Server Mechanics"
    s.cli = ["-u", "--user"]
    s.validator = validate_string
    s.default = None
    s.fmt_desc("""\
        Switch worker processes to run as this user.
        
        A valid user id (as an integer) or the name of a user that can be
        retrieved with a call to pwd.getpwnam(value) or None to not change the
        worker process user.
        """)

with Setting("group") as s:
    s.section = "Server Mechanics"
    s.cli = ["-g", "--group"]
    s.validator = validate_string
    s.default = None
    s.fmt_desc("""\
        Switch worker process to run as this group.
        
        A valid group id (as an integer) or the name of a user that can be
        retrieved with a call to pwd.getgrnam(value) or None to change the
        worker processes group.
        """)

with Setting("umask") as s:
    s.section = "Server Mechanics"
    s.cli = ["-m", "--umask"]
    s.meta = "INT"
    s.validator = validate_pos_int
    s.type = "int"
    s.default = 0
    s.fmt_desc("""\
        A bit mask for the file mode on files written by Gunicorn.
        
        Note that this affects unix socket permissions.
        
        A valid value for the os.umask(mode) call or a string compatible with
        int(value, 0) (0 means Python guesses the base, so values like "0",
        "0xFF", "0022" are valid for decimal, hex, and octal representations)
        """)

with Setting("tmp_upload_dir") as s:
    s.section = "Server Mechanics"
    s.meta = "DIR"
    s.validator = validate_string
    s.default = None
    s.fmt_desc("""\
        Directory to store temporary request data as they are read.
        
        This may disappear in the near future.
        
        This path should be writable by the process permissions set for Gunicorn
        workers. If not specified, Gunicorn will choose a system generated
        temporary directory.
        """)

with Setting("logfile") as s:
    s.section = "Logging"
    s.cli = ["--log-file"]
    s.meta = "FILE"
    s.validator = validate_string
    s.default = "-"
    s.fmt_desc("""\
        The log file to write to.
        
        "-" means log to stdout.
        """)

with Setting("loglevel") as s:
    s.section = "Logging"
    s.cli = ["--log-level"]
    s.meta = "LEVEL"
    s.validator = validate_string
    s.default = "info"
    s.fmt_desc("""\
        The granularity of log output
        
        Valid level names are:
        
        * debug
        * info
        * warning
        * error
        * critical
        """)

with Setting("proc_name") as s:
    s.section = "Process Naming"
    s.cli = ["-n", "--name"]
    s.meta = "STRING"
    s.validator = validate_string
    s.default = "gunicorn"
    s.fmt_desc("""\
        A base to use with setproctitle for process naming.
        
        This affects things like 'ps' and 'top'. If you're going to be running
        more than one instance of Gunicorn you'll probably want to set a name to
        tell them apart. This requires that you install the setproctitle module.
        
        It defaults to 'gunicorn'.
        """)

with Setting("default_proc_name") as s:
    s.section = "Process Naming"
    s.validator = validate_string
    s.default = "gunicorn"
    s.fmt_desc("""\
        Internal setting that is adjusted for each type of application.
        """)

with Setting("pre_fork") as s:
    s.section = "Server Hooks"
    s.validator = validate_callable(2)
    s.type = "callable"
    def def_pre_fork(server, worker):
        pass
    s.default = def_pre_fork
    s.fmt_desc("""\
        Called just before a worker is forked.
        
        The callable needs to accept two instance variables for the Arbiter and
        new Worker.
        """)

with Setting("post_fork") as s:
    s.section = "Server Hooks"
    s.validator = validate_callable(2)
    s.type = "callable"
    def def_post_fork(server, worker):
        server.log.info("Worker spawned (pid: %s)" % worker.pid)
    s.default = def_post_fork
    s.fmt_desc("""\
        Called just after a worker has been forked.
        
        The callable needs to accept two instance variables for the Arbiter and
        new Worker.
        """)

with Setting("when_ready") as s:
    s.section = "Server Hooks"
    s.validator = validate_callable(1)
    s.type = "callable"
    def def_start_server(server):
        pass
    s.default = def_start_server
    s.fmt_desc("""\
        Called just after the server is started.
        
        The callable needs to accept a single instance variable for the Arbiter.
        """)

with Setting("pre_exec") as s:
    s.section = "Server Hooks"
    s.validator = validate_callable(1)
    s.type = "callable"
    def def_pre_exec(server):
        server.log.info("Forked child, reexecuting.")
    s.default = def_pre_exec
    s.fmt_desc("""\
        Called just before a new master process is forked.
        
        The callable needs to accept a single instance variable for the Arbiter.
        """)
        
