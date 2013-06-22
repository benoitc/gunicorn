# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import copy
import grp
import inspect
try:
    import argparse
except ImportError: # python 2.6
    from . import argparse_compat as argparse
import os
import pwd
import sys
import textwrap
import types

from gunicorn import __version__
from gunicorn.errors import ConfigError
from gunicorn import six
from gunicorn import util

KNOWN_SETTINGS = []
PLATFORM = sys.platform


def wrap_method(func):
    def _wrapped(instance, *args, **kwargs):
        return func(*args, **kwargs)
    return _wrapped


def make_settings(ignore=None):
    settings = {}
    ignore = ignore or ()
    for s in KNOWN_SETTINGS:
        setting = s()
        if setting.name in ignore:
            continue
        settings[setting.name] = setting.copy()
    return settings


class Config(object):

    def __init__(self, usage=None, prog=None):
        self.settings = make_settings()
        self.usage = usage
        self.prog = prog or os.path.basename(sys.argv[0])

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
            "prog": self.prog
        }
        parser = argparse.ArgumentParser(**kwargs)
        parser.add_argument("-v", "--version",
                action="version", default=argparse.SUPPRESS,
                version="%(prog)s (version " +  __version__ + ")\n",
                help="show program's version number and exit")
        parser.add_argument("args", nargs="*", help=argparse.SUPPRESS)

        keys = list(self.settings)
        def sorter(k):
            return (self.settings[k].section, self.settings[k].order)

        keys = sorted(self.settings, key=self.settings.__getitem__)
        for k in keys:
            self.settings[k].add_option(parser)

        return parser

    @property
    def worker_class(self):
        uri = self.settings['worker_class'].get()
        worker_class = util.load_class(uri)
        if hasattr(worker_class, "setup"):
            worker_class.setup()
        return worker_class

    @property
    def workers(self):
        return self.settings['workers'].get()

    @property
    def address(self):
        s = self.settings['bind'].get()
        return [util.parse_address(six.bytes_to_str(bind)) for bind in s]

    @property
    def uid(self):
        return self.settings['user'].get()

    @property
    def gid(self):
        return self.settings['group'].get()

    @property
    def proc_name(self):
        pn = self.settings['proc_name'].get()
        if pn is not None:
            return pn
        else:
            return self.settings['default_proc_name'].get()

    @property
    def logger_class(self):
        uri = self.settings['logger_class'].get()
        logger_class = util.load_class(uri, default="simple",
            section="gunicorn.loggers")

        if hasattr(logger_class, "install"):
            logger_class.install()
        return logger_class

    @property
    def is_ssl(self):
        return self.certfile or self.keyfile

    @property
    def ssl_options(self):
        opts = {}
        if self.certfile:
            opts['certfile'] = self.certfile

        if self.keyfile:
            opts['keyfile'] = self.keyfile

        return opts


class SettingMeta(type):
    def __new__(cls, name, bases, attrs):
        super_new = super(SettingMeta, cls).__new__
        parents = [b for b in bases if isinstance(b, SettingMeta)]
        if not parents:
            return super_new(cls, name, bases, attrs)

        attrs["order"] = len(KNOWN_SETTINGS)
        attrs["validator"] = wrap_method(attrs["validator"])

        new_class = super_new(cls, name, bases, attrs)
        new_class.fmt_desc(attrs.get("desc", ""))
        KNOWN_SETTINGS.append(new_class)
        return new_class

    def fmt_desc(cls, desc):
        desc = textwrap.dedent(desc).strip()
        setattr(cls, "desc", desc)
        setattr(cls, "short", desc.splitlines()[0])


class Setting(object):
    name = None
    value = None
    section = None
    cli = None
    validator = None
    type = None
    meta = None
    action = None
    default = None
    short = None
    desc = None
    nargs = None
    const = None



    def __init__(self):
        if self.default is not None:
            self.set(self.default)

    def add_option(self, parser):
        if not self.cli:
            return
        args = tuple(self.cli)

        help_txt = "%s [%s]" % (self.short, self.default)
        help_txt = help_txt.replace("%", "%%")

        kwargs = {
            "dest": self.name,
            "action": self.action or "store",
            "type": self.type or str,
            "default": None,
            "help": help_txt
        }

        if self.meta is not None:
            kwargs['metavar'] = self.meta

        if kwargs["action"] != "store":
            kwargs.pop("type")

        if self.nargs is not None:
            kwargs["nargs"] = self.nargs

        if self.const is not None:
            kwargs["const"] = self.const

        parser.add_argument(*args, **kwargs)

    def copy(self):
        return copy.copy(self)

    def get(self):
        return self.value

    def set(self, val):
        assert six.callable(self.validator), "Invalid validator: %s" % self.name
        self.value = self.validator(val)

    def __lt__(self, other):
        return (self.section == other.section and
                self.order < other.order)
    __cmp__ = __lt__

Setting = SettingMeta('Setting', (Setting,), {})


def validate_bool(val):
    if isinstance(val, bool):
        return val
    if not isinstance(val, six.string_types):
        raise TypeError("Invalid type for casting: %s" % val)
    if val.lower().strip() == "true":
        return True
    elif val.lower().strip() == "false":
        return False
    else:
        raise ValueError("Invalid boolean: %s" % val)


def validate_dict(val):
    if not isinstance(val, dict):
        raise TypeError("Value is not a dictionary: %s " % val)
    return val


def validate_pos_int(val):
    if not isinstance(val, six.integer_types):
        val = int(val, 0)
    else:
        # Booleans are ints!
        val = int(val)
    if val < 0:
        raise ValueError("Value must be positive: %s" % val)
    return val


def validate_string(val):
    if val is None:
        return None
    if not isinstance(val, six.string_types):
        raise TypeError("Not a string: %s" % val)
    return val.strip()


def validate_list_string(val):
    if not val:
        return []

    # legacy syntax
    if isinstance(val, six.string_types):
        val = [val]

    return [validate_string(v) for v in val]


def validate_string_to_list(val):
    val = validate_string(val)

    if not val:
        return []

    return [v.strip() for v in val.split(",") if v]


def validate_class(val):
    if inspect.isfunction(val) or inspect.ismethod(val):
        val = val()
    if inspect.isclass(val):
        return val
    return validate_string(val)


def validate_callable(arity):
    def _validate_callable(val):
        if isinstance(val, six.string_types):
            try:
                mod_name, obj_name = val.rsplit(".", 1)
            except ValueError:
                raise TypeError("Value '%s' is not import string. "
                                "Format: module[.submodules...].object" % val)
            try:
                mod = __import__(mod_name, fromlist=[obj_name])
                val = getattr(mod, obj_name)
            except ImportError as e:
                raise TypeError(str(e))
            except AttributeError:
                raise TypeError("Can not load '%s' from '%s'"
                    "" % (obj_name, mod_name))
        if not six.callable(val):
            raise TypeError("Value is not six.callable: %s" % val)
        if arity != -1 and arity != len(inspect.getargspec(val)[0]):
            raise TypeError("Value must have an arity of: %s" % arity)
        return val
    return _validate_callable


def validate_user(val):
    if val is None:
        return os.geteuid()
    if isinstance(val, int):
        return val
    elif val.isdigit():
        return int(val)
    else:
        try:
            return pwd.getpwnam(val).pw_uid
        except KeyError:
            raise ConfigError("No such user: '%s'" % val)


def validate_group(val):
    if val is None:
        return os.getegid()

    if isinstance(val, int):
        return val
    elif val.isdigit():
        return int(val)
    else:
        try:
            return grp.getgrnam(val).gr_gid
        except KeyError:
            raise ConfigError("No such group: '%s'" % val)


def validate_post_request(val):
    val = validate_callable(-1)(val)

    largs = len(inspect.getargspec(val)[0])
    if largs == 4:
        return val
    elif largs == 3:
        return lambda worker, req, env, _r: val(worker, req, env)
    elif largs == 2:
        return lambda worker, req, _e, _r: val(worker, req)
    else:
        raise TypeError("Value must have an arity of: 4")

def get_default_config_file():
    config_path = os.path.join(os.path.abspath(os.getcwd()), 'gunicorn.conf.py')
    if os.path.exists(config_path):
        return config_path
    return None


class ConfigFile(Setting):
    name = "config"
    section = "Config File"
    cli = ["-c", "--config"]
    meta = "FILE"
    validator = validate_string
    default = None
    desc = """\
        The path to a Gunicorn config file.

        Only has an effect when specified on the command line or as part of an
        application specific configuration.
        """

class Bind(Setting):
    name = "bind"
    action = "append"
    section = "Server Socket"
    cli = ["-b", "--bind"]
    meta = "ADDRESS"
    validator = validate_list_string

    if 'PORT' in os.environ:
        default = ['0.0.0.0:{0}'.format(os.environ.get('PORT'))]
    else:
        default = ['127.0.0.1:8000']

    desc = """\
        The socket to bind.

        A string of the form: 'HOST', 'HOST:PORT', 'unix:PATH'. An IP is a valid
        HOST.

        Multiple addresses can be bound. ex.::

            $ gunicorn -b 127.0.0.1:8000 -b [::1]:8000 test:app

        will bind the `test:app` application on localhost both on ipv6
        and ipv4 interfaces.
        """


class Backlog(Setting):
    name = "backlog"
    section = "Server Socket"
    cli = ["--backlog"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 2048
    desc = """\
        The maximum number of pending connections.

        This refers to the number of clients that can be waiting to be served.
        Exceeding this number results in the client getting an error when
        attempting to connect. It should only affect servers under significant
        load.

        Must be a positive integer. Generally set in the 64-2048 range.
        """


class Workers(Setting):
    name = "workers"
    section = "Worker Processes"
    cli = ["-w", "--workers"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 1
    desc = """\
        The number of worker process for handling requests.

        A positive integer generally in the 2-4 x $(NUM_CORES) range. You'll
        want to vary this a bit to find the best for your particular
        application's work load.
        """


class WorkerClass(Setting):
    name = "worker_class"
    section = "Worker Processes"
    cli = ["-k", "--worker-class"]
    meta = "STRING"
    validator = validate_class
    default = "sync"
    desc = """\
        The type of workers to use.

        The default class (sync) should handle most 'normal' types of
        workloads.  You'll want to read
        http://docs.gunicorn.org/en/latest/design.html for information
        on when you might want to choose one of the other worker
        classes.

        A string referring to one of the following bundled classes:

        * ``sync``
        * ``eventlet`` - Requires eventlet >= 0.9.7
        * ``gevent``   - Requires gevent >= 0.12.2 (?)
        * ``tornado``  - Requires tornado >= 0.2

        Optionally, you can provide your own worker by giving gunicorn a
        python path to a subclass of gunicorn.workers.base.Worker. This
        alternative syntax will load the gevent class:
        ``gunicorn.workers.ggevent.GeventWorker``. Alternatively the syntax
        can also load the gevent class with ``egg:gunicorn#gevent``
        """


class WorkerConnections(Setting):
    name = "worker_connections"
    section = "Worker Processes"
    cli = ["--worker-connections"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 1000
    desc = """\
        The maximum number of simultaneous clients.

        This setting only affects the Eventlet and Gevent worker types.
        """


class MaxRequests(Setting):
    name = "max_requests"
    section = "Worker Processes"
    cli = ["--max-requests"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 0
    desc = """\
        The maximum number of requests a worker will process before restarting.

        Any value greater than zero will limit the number of requests a work
        will process before automatically restarting. This is a simple method
        to help limit the damage of memory leaks.

        If this is set to zero (the default) then the automatic worker
        restarts are disabled.
        """


class Timeout(Setting):
    name = "timeout"
    section = "Worker Processes"
    cli = ["-t", "--timeout"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 30
    desc = """\
        Workers silent for more than this many seconds are killed and restarted.

        Generally set to thirty seconds. Only set this noticeably higher if
        you're sure of the repercussions for sync workers. For the non sync
        workers it just means that the worker process is still communicating and
        is not tied to the length of time required to handle a single request.
        """


class GracefulTimeout(Setting):
    name = "graceful_timeout"
    section = "Worker Processes"
    cli = ["--graceful-timeout"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 30
    desc = """\
        Timeout for graceful workers restart.

        Generally set to thirty seconds. How max time worker can handle
        request after got restart signal. If the time is up worker will
        be force killed.
        """


class Keepalive(Setting):
    name = "keepalive"
    section = "Worker Processes"
    cli = ["--keep-alive"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 2
    desc = """\
        The number of seconds to wait for requests on a Keep-Alive connection.

        Generally set in the 1-5 seconds range.
        """


class LimitRequestLine(Setting):
    name = "limit_request_line"
    section = "Security"
    cli = ["--limit-request-line"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 4094
    desc = """\
        The maximum size of HTTP request line in bytes.

        This parameter is used to limit the allowed size of a client's
        HTTP request-line. Since the request-line consists of the HTTP
        method, URI, and protocol version, this directive places a
        restriction on the length of a request-URI allowed for a request
        on the server. A server needs this value to be large enough to
        hold any of its resource names, including any information that
        might be passed in the query part of a GET request. Value is a number
        from 0 (unlimited) to 8190.

        This parameter can be used to prevent any DDOS attack.
        """


class LimitRequestFields(Setting):
    name = "limit_request_fields"
    section = "Security"
    cli = ["--limit-request-fields"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 100
    desc = """\
        Limit the number of HTTP headers fields in a request.

        This parameter is used to limit the number of headers in a request to
        prevent DDOS attack. Used with the `limit_request_field_size` it allows
        more safety. By default this value is 100 and can't be larger than
        32768.
        """


class LimitRequestFieldSize(Setting):
    name = "limit_request_field_size"
    section = "Security"
    cli = ["--limit-request-field_size"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 8190
    desc = """\
        Limit the allowed size of an HTTP request header field.

        Value is a number from 0 (unlimited) to 8190. to set the limit
        on the allowed size of an HTTP request header field.
        """


class Debug(Setting):
    name = "debug"
    section = "Debugging"
    cli = ["--debug"]
    validator = validate_bool
    action = "store_true"
    default = False
    desc = """\
        Turn on debugging in the server.

        This limits the number of worker processes to 1 and changes some error
        handling that's sent to clients.
        """


class Spew(Setting):
    name = "spew"
    section = "Debugging"
    cli = ["--spew"]
    validator = validate_bool
    action = "store_true"
    default = False
    desc = """\
        Install a trace function that spews every line executed by the server.

        This is the nuclear option.
        """


class ConfigCheck(Setting):
    name = "check_config"
    section = "Debugging"
    cli = ["--check-config", ]
    validator = validate_bool
    action = "store_true"
    default = False
    desc = """\
        Check the configuration..
        """


class PreloadApp(Setting):
    name = "preload_app"
    section = "Server Mechanics"
    cli = ["--preload"]
    validator = validate_bool
    action = "store_true"
    default = False
    desc = """\
        Load application code before the worker processes are forked.

        By preloading an application you can save some RAM resources as well as
        speed up server boot times. Although, if you defer application loading
        to each worker process, you can reload your application code easily by
        restarting workers.
        """


class Daemon(Setting):
    name = "daemon"
    section = "Server Mechanics"
    cli = ["-D", "--daemon"]
    validator = validate_bool
    action = "store_true"
    default = False
    desc = """\
        Daemonize the Gunicorn process.

        Detaches the server from the controlling terminal and enters the
        background.
        """


class Pidfile(Setting):
    name = "pidfile"
    section = "Server Mechanics"
    cli = ["-p", "--pid"]
    meta = "FILE"
    validator = validate_string
    default = None
    desc = """\
        A filename to use for the PID file.

        If not set, no PID file will be written.
        """


class User(Setting):
    name = "user"
    section = "Server Mechanics"
    cli = ["-u", "--user"]
    meta = "USER"
    validator = validate_user
    default = os.geteuid()
    desc = """\
        Switch worker processes to run as this user.

        A valid user id (as an integer) or the name of a user that can be
        retrieved with a call to pwd.getpwnam(value) or None to not change
        the worker process user.
        """


class Group(Setting):
    name = "group"
    section = "Server Mechanics"
    cli = ["-g", "--group"]
    meta = "GROUP"
    validator = validate_group
    default = os.getegid()
    desc = """\
        Switch worker process to run as this group.

        A valid group id (as an integer) or the name of a user that can be
        retrieved with a call to pwd.getgrnam(value) or None to not change
        the worker processes group.
        """


class Umask(Setting):
    name = "umask"
    section = "Server Mechanics"
    cli = ["-m", "--umask"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 0
    desc = """\
        A bit mask for the file mode on files written by Gunicorn.

        Note that this affects unix socket permissions.

        A valid value for the os.umask(mode) call or a string compatible with
        int(value, 0) (0 means Python guesses the base, so values like "0",
        "0xFF", "0022" are valid for decimal, hex, and octal representations)
        """


class TmpUploadDir(Setting):
    name = "tmp_upload_dir"
    section = "Server Mechanics"
    meta = "DIR"
    validator = validate_string
    default = None
    desc = """\
        Directory to store temporary request data as they are read.

        This may disappear in the near future.

        This path should be writable by the process permissions set for Gunicorn
        workers. If not specified, Gunicorn will choose a system generated
        temporary directory.
        """


class SecureSchemeHeader(Setting):
    name = "secure_scheme_headers"
    section = "Server Mechanics"
    validator = validate_dict
    default = {
        "X-FORWARDED-PROTOCOL": "ssl",
        "X-FORWARDED-PROTO": "https",
        "X-FORWARDED-SSL": "on"
    }
    desc = """\

        A dictionary containing headers and values that the front-end proxy
        uses to indicate HTTPS requests. These tell gunicorn to set
        wsgi.url_scheme to "https", so your application can tell that the
        request is secure.

        The dictionary should map upper-case header names to exact string
        values. The value comparisons are case-sensitive, unlike the header
        names, so make sure they're exactly what your front-end proxy sends
        when handling HTTPS requests.

        It is important that your front-end proxy configuration ensures that
        the headers defined here can not be passed directly from the client.
        """


class XForwardedFor(Setting):
    name = "x_forwarded_for_header"
    section = "Server Mechanics"
    meta = "STRING"
    validator = validate_string
    default = 'X-FORWARDED-FOR'
    desc = """\
        Set the X-Forwarded-For header that identify the originating IP
        address of the client connection to gunicorn via a proxy.
        """


class ForwardedAllowIPS(Setting):
    name = "forwarded_allow_ips"
    section = "Server Mechanics"
    meta = "STRING"
    validator = validate_string_to_list
    default = "127.0.0.1"
    desc = """\
        Front-end's IPs from which allowed to handle X-Forwarded-* headers.
        (comma separate).

        Set to "*" to disable checking of Front-end IPs (useful for setups
        where you don't know in advance the IP address of Front-end, but
        you still trust the environment)
        """


class AccessLog(Setting):
    name = "accesslog"
    section = "Logging"
    cli = ["--access-logfile"]
    meta = "FILE"
    validator = validate_string
    default = None
    desc = """\
        The Access log file to write to.

        "-" means log to stderr.
        """


class AccessLogFormat(Setting):
    name = "access_log_format"
    section = "Logging"
    cli = ["--access-logformat"]
    meta = "STRING"
    validator = validate_string
    default = '"%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'
    desc = """\
        The Access log format .

        By default:

        %(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"


        h: remote address
        l: '-'
        u: currently '-', may be user name in future releases
        t: date of the request
        r: status line (ex: GET / HTTP/1.1)
        s: status
        b: response length or '-'
        f: referer
        a: user agent
        T: request time in seconds
        D: request time in microseconds,
        p: process ID
        {Header}i: request header
        {Header}o: response header
        """


class ErrorLog(Setting):
    name = "errorlog"
    section = "Logging"
    cli = ["--error-logfile", "--log-file"]
    meta = "FILE"
    validator = validate_string
    default = "-"
    desc = """\
        The Error log file to write to.

        "-" means log to stderr.
        """


class Loglevel(Setting):
    name = "loglevel"
    section = "Logging"
    cli = ["--log-level"]
    meta = "LEVEL"
    validator = validate_string
    default = "info"
    desc = """\
        The granularity of Error log outputs.

        Valid level names are:

        * debug
        * info
        * warning
        * error
        * critical
        """


class LoggerClass(Setting):
    name = "logger_class"
    section = "Logging"
    cli = ["--logger-class"]
    meta = "STRING"
    validator = validate_class
    default = "simple"
    desc = """\
        The logger you want to use to log events in gunicorn.

        The default class (``gunicorn.glogging.Logger``) handle most of
        normal usages in logging. It provides error and access logging.

        You can provide your own worker by giving gunicorn a
        python path to a subclass like gunicorn.glogging.Logger.
        Alternatively the syntax can also load the Logger class
        with `egg:gunicorn#simple`
        """


class LogConfig(Setting):
    name = "logconfig"
    section = "Logging"
    cli = ["--log-config"]
    meta = "FILE"
    validator = validate_string
    default = None
    desc = """\
The log config file to use.
Gunicorn uses the standard Python logging module's Configuration
file format.
"""

class SyslogTo(Setting):
    name = "syslog_addr"
    section = "Logging"
    cli = ["--log-syslog-to"]
    meta = "SYSLOG_ADDR"
    validator = validate_string

    if PLATFORM == "darwin":
        default = "unix:///var/run/syslog"
    elif PLATFORM in ('freebsd', 'dragonfly', ):
        default = "unix:///var/run/log"
    elif PLATFORM == "openbsd":
        default = "unix:///dev/log"
    else:
        default = "udp://localhost:514"

    desc = """\
    Address to send syslog messages
    """


class Syslog(Setting):
    name = "syslog"
    section = "Logging"
    cli = ["--log-syslog"]
    validator = validate_bool
    action = 'store_true'
    default = False
    desc = """\
    Log to syslog.
    """


class SyslogPrefix(Setting):
    name = "syslog_prefix"
    section = "Logging"
    cli = ["--log-syslog-prefix"]
    meta = "SYSLOG_PREFIX"
    validator = validate_string
    default = None
    desc = """\
    makes gunicorn use the parameter as program-name in the syslog entries.

    All entries will be prefixed by gunicorn.<prefix>. By default the program
    name is the name of the process.
    """


class SyslogFacility(Setting):
    name = "syslog_facility"
    section = "Logging"
    cli = ["--log-syslog-facility"]
    meta = "SYSLOG_FACILITY"
    validator = validate_string
    default = "user"
    desc = """\
    Syslog facility name
    """


class EnableStdioInheritance(Setting):
    name = "enable_stdio_inheritance"
    section = "Logging"
    cli = ["-R", "--enable-stdio-inheritance"]
    validator = validate_bool
    default = False
    action = "store_true"
    desc = """\
    Enable stdio inheritance

    Enable inheritance for stdio file descriptors in daemon mode.

    Note: To disable the python stdout buffering, you can to set the user
    environment variable ``PYTHONUNBUFFERED`` .
    """


class Procname(Setting):
    name = "proc_name"
    section = "Process Naming"
    cli = ["-n", "--name"]
    meta = "STRING"
    validator = validate_string
    default = None
    desc = """\
        A base to use with setproctitle for process naming.

        This affects things like ``ps`` and ``top``. If you're going to be
        running more than one instance of Gunicorn you'll probably want to set a
        name to tell them apart. This requires that you install the setproctitle
        module.

        It defaults to 'gunicorn'.
        """


class DefaultProcName(Setting):
    name = "default_proc_name"
    section = "Process Naming"
    validator = validate_string
    default = "gunicorn"
    desc = """\
        Internal setting that is adjusted for each type of application.
        """


class DjangoSettings(Setting):
    name = "django_settings"
    section = "Django"
    cli = ["--settings"]
    meta = "STRING"
    validator = validate_string
    default = None
    desc = """\
        The Python path to a Django settings module.

        e.g. 'myproject.settings.main'. If this isn't provided, the
        DJANGO_SETTINGS_MODULE environment variable will be used.
        """


class PythonPath(Setting):
    name = "pythonpath"
    section = "Server Mechanics"
    cli = ["--pythonpath"]
    meta = "STRING"
    validator = validate_string
    default = None
    desc = """\
        A directory to add to the Python path for Django.

        e.g.
        '/home/djangoprojects/myproject'.
        """


class OnStarting(Setting):
    name = "on_starting"
    section = "Server Hooks"
    validator = validate_callable(1)
    type = six.callable

    def on_starting(server):
        pass
    default = staticmethod(on_starting)
    desc = """\
        Called just before the master process is initialized.

        The callable needs to accept a single instance variable for the Arbiter.
        """


class OnReload(Setting):
    name = "on_reload"
    section = "Server Hooks"
    validator = validate_callable(1)
    type = six.callable

    def on_reload(server):
        pass
    default = staticmethod(on_reload)
    desc = """\
        Called to recycle workers during a reload via SIGHUP.

        The callable needs to accept a single instance variable for the Arbiter.
        """


class WhenReady(Setting):
    name = "when_ready"
    section = "Server Hooks"
    validator = validate_callable(1)
    type = six.callable

    def when_ready(server):
        pass
    default = staticmethod(when_ready)
    desc = """\
        Called just after the server is started.

        The callable needs to accept a single instance variable for the Arbiter.
        """


class Prefork(Setting):
    name = "pre_fork"
    section = "Server Hooks"
    validator = validate_callable(2)
    type = six.callable

    def pre_fork(server, worker):
        pass
    default = staticmethod(pre_fork)
    desc = """\
        Called just before a worker is forked.

        The callable needs to accept two instance variables for the Arbiter and
        new Worker.
        """


class Postfork(Setting):
    name = "post_fork"
    section = "Server Hooks"
    validator = validate_callable(2)
    type = six.callable

    def post_fork(server, worker):
        pass
    default = staticmethod(post_fork)
    desc = """\
        Called just after a worker has been forked.

        The callable needs to accept two instance variables for the Arbiter and
        new Worker.
        """


class PostWorkerInit(Setting):
    name = "post_worker_init"
    section = "Server Hooks"
    validator = validate_callable(1)
    type = six.callable

    def post_worker_init(worker):
        pass

    default = staticmethod(post_worker_init)
    desc = """\
        Called just after a worker has initialized the application.

        The callable needs to accept one instance variable for the initialized
        Worker.
        """


class PreExec(Setting):
    name = "pre_exec"
    section = "Server Hooks"
    validator = validate_callable(1)
    type = six.callable

    def pre_exec(server):
        pass
    default = staticmethod(pre_exec)
    desc = """\
        Called just before a new master process is forked.

        The callable needs to accept a single instance variable for the Arbiter.
        """


class PreRequest(Setting):
    name = "pre_request"
    section = "Server Hooks"
    validator = validate_callable(2)
    type = six.callable

    def pre_request(worker, req):
        worker.log.debug("%s %s" % (req.method, req.path))
    default = staticmethod(pre_request)
    desc = """\
        Called just before a worker processes the request.

        The callable needs to accept two instance variables for the Worker and
        the Request.
        """


class PostRequest(Setting):
    name = "post_request"
    section = "Server Hooks"
    validator = validate_post_request
    type = six.callable

    def post_request(worker, req, environ, resp):
        pass
    default = staticmethod(post_request)
    desc = """\
        Called after a worker processes the request.

        The callable needs to accept two instance variables for the Worker and
        the Request.
        """


class WorkerExit(Setting):
    name = "worker_exit"
    section = "Server Hooks"
    validator = validate_callable(2)
    type = six.callable

    def worker_exit(server, worker):
        pass
    default = staticmethod(worker_exit)
    desc = """\
        Called just after a worker has been exited.

        The callable needs to accept two instance variables for the Arbiter and
        the just-exited Worker.
        """


class NumWorkersChanged(Setting):
    name = "nworkers_changed"
    section = "Server Hooks"
    validator = validate_callable(3)
    type = six.callable

    def nworkers_changed(server, new_value, old_value):
        pass
    default = staticmethod(nworkers_changed)
    desc = """\
        Called just after num_workers has been changed.

        The callable needs to accept an instance variable of the Arbiter and
        two integers of number of workers after and before change.

        If the number of workers is set for the first time, old_value would be
        None.
        """


class ProxyProtocol(Setting):
    name = "proxy_protocol"
    section = "Server Mechanics"
    cli = ["--proxy-protocol"]
    validator = validate_bool
    default = False
    action = "store_true"
    desc = """\
        Enable detect PROXY protocol (PROXY mode).

        Allow using Http and Proxy together. It's may be useful for work with
        stunnel as https frondend and gunicorn as http server.

        PROXY protocol: http://haproxy.1wt.eu/download/1.5/doc/proxy-protocol.txt

        Example for stunnel config::

        [https]
        protocol = proxy
        accept  = 443
        connect = 80
        cert = /etc/ssl/certs/stunnel.pem
        key = /etc/ssl/certs/stunnel.key
        """


class ProxyAllowFrom(Setting):
    name = "proxy_allow_ips"
    section = "Server Mechanics"
    cli = ["--proxy-allow-from"]
    validator = validate_string_to_list
    default = "127.0.0.1"
    desc = """\
        Front-end's IPs from which allowed accept proxy requests (comma separate).
        """


class KeyFile(Setting):
    name = "keyfile"
    section = "Ssl"
    cli = ["--keyfile"]
    meta = "FILE"
    validator = validate_string
    default = None
    desc = """\
    SSL key file
    """


class CertFile(Setting):
    name = "certfile"
    section = "Ssl"
    cli = ["--certfile"]
    meta = "FILE"
    validator = validate_string
    default = None
    desc = """\
    SSL certificate file
    """
