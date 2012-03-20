# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.


try:
    import ctypes
except MemoryError:
    # selinux execmem denial
    # https://bugzilla.redhat.com/show_bug.cgi?id=488396
    ctypes = None
except ImportError:
    # Python on Solaris compiled with Sun Studio doesn't have ctypes
    ctypes = None

import fcntl
import os
import pkg_resources
import random
import resource
import socket
import sys
import textwrap
import time
import inspect


MAXFD = 1024
if (hasattr(os, "devnull")):
   REDIRECT_TO = os.devnull
else:
   REDIRECT_TO = "/dev/null"

timeout_default = object()

CHUNK_SIZE = (16 * 1024)

MAX_BODY = 1024 * 132

weekdayname = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
monthname = [None,
             'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

# Server and Date aren't technically hop-by-hop
# headers, but they are in the purview of the
# origin server which the WSGI spec says we should
# act like. So we drop them and add our own.
#
# In the future, concatenation server header values
# might be better, but nothing else does it and
# dropping them is easier.
hop_headers = set("""
    connection keep-alive proxy-authenticate proxy-authorization
    te trailers transfer-encoding upgrade
    server date
    """.split())

try:
    from setproctitle import setproctitle
    def _setproctitle(title):
        setproctitle("gunicorn: %s" % title)
except ImportError:
    def _setproctitle(title):
        return


try:
    from importlib import import_module
except ImportError:
    def _resolve_name(name, package, level):
        """Return the absolute name of the module to be imported."""
        if not hasattr(package, 'rindex'):
            raise ValueError("'package' not set to a string")
        dot = len(package)
        for x in xrange(level, 1, -1):
            try:
                dot = package.rindex('.', 0, dot)
            except ValueError:
                raise ValueError("attempted relative import beyond top-level "
                                  "package")
        return "%s.%s" % (package[:dot], name)


    def import_module(name, package=None):
        """Import a module.

The 'package' argument is required when performing a relative import. It
specifies the package to use as the anchor point from which to resolve the
relative import to an absolute import.

"""
        if name.startswith('.'):
            if not package:
                raise TypeError("relative imports require the 'package' argument")
            level = 0
            for character in name:
                if character != '.':
                    break
                level += 1
            name = _resolve_name(name[level:], package, level)
        __import__(name)
        return sys.modules[name]

def load_class(uri, default="sync", section="gunicorn.workers"):
    if inspect.isclass(uri):
        return uri
    if uri.startswith("egg:"):
        # uses entry points
        entry_str = uri.split("egg:")[1]
        try:
            dist, name = entry_str.rsplit("#",1)
        except ValueError:
            dist = entry_str
            name = default

        return pkg_resources.load_entry_point(dist, section, name)
    else:
        components = uri.split('.')
        if len(components) == 1:
            try:
                if uri.startswith("#"):
                    uri = uri[1:]

                return pkg_resources.load_entry_point("gunicorn",
                            section, uri)
            except ImportError:
                raise RuntimeError("class uri invalid or not found")
        klass = components.pop(-1)
        mod = __import__('.'.join(components))
        for comp in components[1:]:
            mod = getattr(mod, comp)
        return getattr(mod, klass)

def set_owner_process(uid,gid):
    """ set user and group of workers processes """
    if gid:
        try:
            os.setgid(gid)
        except OverflowError:
            if not ctypes:
                raise
            # versions of python < 2.6.2 don't manage unsigned int for
            # groups like on osx or fedora
            os.setgid(-ctypes.c_int(-gid).value)

    if uid:
        os.setuid(uid)

def chown(path, uid, gid):
    try:
        os.chown(path, uid, gid)
    except OverflowError:
        if not ctypes:
            raise
        os.chown(path, uid, -ctypes.c_int(-gid).value)


def is_ipv6(addr):
    try:
        socket.inet_pton(socket.AF_INET6, addr)
    except socket.error: # not a valid address
        return False
    return True

def parse_address(netloc, default_port=8000):
    if netloc.startswith("unix:"):
        return netloc.split("unix:")[1]

    # get host
    if '[' in netloc and ']' in netloc:
        host = netloc.split(']')[0][1:].lower()
    elif ':' in netloc:
        host = netloc.split(':')[0].lower()
    elif netloc == "":
        host = "0.0.0.0"
    else:
        host = netloc.lower()

    #get port
    netloc = netloc.split(']')[-1]
    if ":" in netloc:
        port = netloc.split(':', 1)[1]
        if not port.isdigit():
            raise RuntimeError("%r is not a valid port number." % port)
        port = int(port)
    else:
        port = default_port
    return (host, port)

def get_maxfd():
    maxfd = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
    if (maxfd == resource.RLIM_INFINITY):
        maxfd = MAXFD
    return maxfd

def close_on_exec(fd):
    flags = fcntl.fcntl(fd, fcntl.F_GETFD)
    flags |= fcntl.FD_CLOEXEC
    fcntl.fcntl(fd, fcntl.F_SETFD, flags)

def set_non_blocking(fd):
    flags = fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK
    fcntl.fcntl(fd, fcntl.F_SETFL, flags)

def close(sock):
    try:
        sock.close()
    except socket.error:
        pass

try:
    from os import closerange
except ImportError:
    def closerange(fd_low, fd_high):
        # Iterate through and close all file descriptors.
        for fd in xrange(fd_low, fd_high):
            try:
                os.close(fd)
            except OSError:	# ERROR, fd wasn't open to begin with (ignored)
                pass

def write_chunk(sock, data):
    chunk = "".join(("%X\r\n" % len(data), data, "\r\n"))
    sock.sendall(chunk)

def write(sock, data, chunked=False):
    if chunked:
        return write_chunk(sock, data)
    sock.sendall(data)

def write_nonblock(sock, data, chunked=False):
    timeout = sock.gettimeout()
    if timeout != 0.0:
        try:
            sock.setblocking(0)
            return write(sock, data, chunked)
        finally:
            sock.setblocking(1)
    else:
        return write(sock, data, chunked)

def writelines(sock, lines, chunked=False):
    for line in list(lines):
        write(sock, line, chunked)

def write_error(sock, status_int, reason, mesg):
    html = textwrap.dedent("""\
    <html>
      <head>
        <title>%(reason)s</title>
      </head>
      <body>
        <h1>%(reason)s</h1>
        %(mesg)s
      </body>
    </html>
    """) % {"reason": reason, "mesg": mesg}

    http = textwrap.dedent("""\
    HTTP/1.1 %s %s\r
    Connection: close\r
    Content-Type: text/html\r
    Content-Length: %d\r
    \r
    %s
    """) % (str(status_int), reason, len(html), html)
    write_nonblock(sock, http)

def normalize_name(name):
    return  "-".join([w.lower().capitalize() for w in name.split("-")])

def import_app(module):
    parts = module.split(":", 1)
    if len(parts) == 1:
        module, obj = module, "application"
    else:
        module, obj = parts[0], parts[1]

    try:
        __import__(module)
    except ImportError:
        if module.endswith(".py") and os.path.exists(module):
            raise ImportError("Failed to find application, did "
                "you mean '%s:%s'?" % (module.rsplit(".",1)[0], obj))
        else:
            raise

    mod = sys.modules[module]
    app = eval(obj, mod.__dict__)
    if app is None:
        raise ImportError("Failed to find application object: %r" % obj)
    if not callable(app):
        raise TypeError("Application object must be callable.")
    return app

def http_date(timestamp=None):
    """Return the current date and time formatted for a message header."""
    if timestamp is None:
        timestamp = time.time()
    year, month, day, hh, mm, ss, wd, y, z = time.gmtime(timestamp)
    s = "%s, %02d %3s %4d %02d:%02d:%02d GMT" % (
            weekdayname[wd],
            day, monthname[month], year,
            hh, mm, ss)
    return s

def to_bytestring(s):
    """ convert to bytestring an unicode """
    if not isinstance(s, basestring):
        return s
    if isinstance(s, unicode):
        return s.encode('utf-8')
    else:
        return s

def is_hoppish(header):
    return header.lower().strip() in hop_headers

def daemonize():
    """\
    Standard daemonization of a process.
    http://www.svbug.com/documentation/comp.unix.programmer-FAQ/faq_2.html#SEC16
    """
    if not 'GUNICORN_FD' in os.environ:
        if os.fork():
            os._exit(0)
        os.setsid()

        if os.fork():
            os._exit(0)

        os.umask(0)
        maxfd = get_maxfd()
        closerange(0, maxfd)

        os.open(REDIRECT_TO, os.O_RDWR)
        os.dup2(0, 1)
        os.dup2(0, 2)

def seed():
    try:
        random.seed(os.urandom(64))
    except NotImplementedError:
        random.seed(random.random())


def check_is_writeable(path):
    try:
        f = open(path, 'a')
    except IOError, e:
        raise RuntimeError("Error: '%s' isn't writable [%r]" % (path, e))
    f.close()
