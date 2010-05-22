# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.


import ctypes
import fcntl
import os
import pkg_resources
import resource
import socket
import textwrap
import time

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

hop_headers = set("""
    connection keep-alive proxy-authenticate proxy-authorization
    te trailers transfer-encoding upgrade
    """.split())
             
try:
    from setproctitle import setproctitle
    def _setproctitle(title):
        setproctitle("gunicorn: %s" % title) 
except ImportError:
    def _setproctitle(title):
        return

def load_worker_class(uri):
    if uri.startswith("egg:"):
        # uses entry points
        entry_str = uri.split("egg:")[1]
        try:
            dist, name = entry_str.rsplit("#",1)
        except ValueError:
            dist = entry_str
            name = "sync"

        return pkg_resources.load_entry_point(dist, "gunicorn.workers", name)
    else:
        components = uri.split('.')
        if len(components) == 1:
            raise RuntimeError("arbiter uri invalid")
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
            # versions of python < 2.6.2 don't manage unsigned int for
            # groups like on osx or fedora
            os.setgid(-ctypes.c_int(-gid).value)
            
    if uid:
        os.setuid(uid)
        
def chown(path, uid, gid):
    try:
        os.chown(path, uid, gid)
    except OverflowError:
        os.chown(path, uid, -ctypes.c_int(-gid).value)
        
def parse_address(host, port=None, default_port=8000):
    if host.startswith("unix:"):
        return host.split("unix:")[1]
        
    if not port:
        if ':' in host:
            host, port = host.split(':', 1)
            if not port.isdigit():
                raise RuntimeError("%r is not a valid port number." % port)
            port = int(port)
        else:
            port = default_port
    return (host, int(port))
    
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

def write_error(sock, msg):
    html = textwrap.dedent("""\
    <html>
        <head>
            <title>Internal Server Error</title>
        </head>
        <body>
            <h1>Internal Server Error</h1>
            <h2>WSGI Error Report:</h2>
            <pre>%s</pre>
        </body>
    </html>
    """) % msg
    http = textwrap.dedent("""\
    HTTP/1.1 500 Internal Server Error\r
    Connection: close\r
    Content-Type: text/html\r
    Content-Length: %d\r
    \r
    %s
    """) % (len(html), html)
    write_nonblock(sock, http)

def normalize_name(name):
    return  "-".join([w.lower().capitalize() for w in name.split("-")])
    
def import_app(module):
    parts = module.rsplit(":", 1)
    if len(parts) == 1:
        module, obj = module, "application"
    else:
        module, obj = parts[0], parts[1]
    mod = __import__(module)
    parts = module.split(".")
    for p in parts[1:]:
        mod = getattr(mod, p, None)
        if mod is None:
            raise ImportError("Failed to import: %s" % module)
    app = getattr(mod, obj, None)
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
    Standard daemonization of a process. Code is basd on the
    ActiveState recipe at:
        http://code.activestate.com/recipes/278731/
    """
    if not 'GUNICORN_FD' in os.environ:
        if os.fork() == 0: 
            os.setsid()
            if os.fork() != 0:
                os.umask(0) 
            else:
                os._exit(0)
        else:
            os._exit(0)
        
        maxfd = get_maxfd()

        # Iterate through and close all file descriptors.
        for fd in range(0, maxfd):
            try:
                os.close(fd)
            except OSError:	# ERROR, fd wasn't open to begin with (ignored)
                pass
        
        os.open(REDIRECT_TO, os.O_RDWR)
        os.dup2(0, 1)
        os.dup2(0, 2)