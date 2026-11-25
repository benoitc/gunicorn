#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""What the platform can do.

gunicorn is a pre-fork server: the arbiter forks workers and steers them
with POSIX signals. Windows has no fork, no POSIX signals and no fcntl, so
the rest of the code asks this module instead of probing os and signal.

    POSIX                          Windows
    -----                          -------
    os.fork()                      absent -> gunicorn.single serves
    SIGCHLD, SIGHUP, SIGUSR1,      only SIGINT, SIGTERM, SIGBREAK,
    SIGUSR2, SIGQUIT, SIGWINCH     SIGABRT
    fcntl FD_CLOEXEC               os.set_inheritable()
    fcntl O_NONBLOCK               os.set_blocking()
    os.geteuid(), os.getegid()     0 (no user and group ids)
"""

import errno
import os
import signal
import sys

WINDOWS = sys.platform.startswith("win")

# Whether a master process can fork workers at all.
HAS_FORK = hasattr(os, "fork")

# select() on Windows fills an fd_set of at most 512 sockets; leave room for
# the listeners and the wakeup queue.
SELECT_MAX_CONNECTIONS = 508 if WINDOWS else None

# A connection the peer or the local stack aborted is not a server error:
# POSIX reports a reset as ECONNRESET, which the workers already ignore, and
# Windows reports the same event as WSAECONNABORTED.
CLIENT_ABORT_ERRNOS = (errno.ECONNABORTED,) if WINDOWS else ()

if not WINDOWS:
    import fcntl


def signals_for(names):
    """The platform's signal values for names, skipping absent ones.

    Windows defines no SIGHUP, SIGQUIT, SIGUSR1, SIGUSR2, SIGWINCH, SIGCHLD,
    SIGTTIN or SIGTTOU; looking one up raises AttributeError.
    """
    found = (getattr(signal, "SIG" + name, None) for name in names)
    return [sig for sig in found if sig is not None]


def geteuid():
    """The effective user id, 0 on Windows where there are none."""
    if WINDOWS:
        return 0
    return os.geteuid()


def getegid():
    """The effective group id, 0 on Windows where there are none."""
    if WINDOWS:
        return 0
    return os.getegid()


def chown(path, uid, gid):
    """Change the owner of path, a no-op on Windows."""
    if WINDOWS:
        return
    os.chown(path, uid, gid)


def pid_running(pid):
    """Whether pid names a live process (Windows only).

    os.kill(pid, 0), the POSIX probe, cannot be used there: every signal but
    Ctrl+C and Ctrl+Break terminates the process. Ask the kernel instead.
    """
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    ERROR_ACCESS_DENIED = 5

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        kernel32.CloseHandle(handle)
        return True

    # Access denied still means the process is there.
    return ctypes.get_last_error() == ERROR_ACCESS_DENIED


def umask(mask):
    """Set the file creation mask and return the old one.

    Windows has no creation mask; nothing to set and nothing to restore.
    """
    if WINDOWS or mask is None:
        return None
    return os.umask(mask)


def close_on_exec(fd):
    """Mark fd to stay out of child processes."""
    if WINDOWS:
        # No FD_CLOEXEC: a handle is inherited only when marked inheritable.
        # A socket's fileno() is a SOCKET handle, not a CRT descriptor, so
        # it needs the socket method; os.set_inheritable takes descriptors.
        if hasattr(fd, "set_inheritable"):
            fd.set_inheritable(False)
        else:
            os.set_inheritable(fd, False)
        return
    flags = fcntl.fcntl(fd, fcntl.F_GETFD)
    fcntl.fcntl(fd, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)


def set_non_blocking(fd):
    """Mark fd non-blocking."""
    if WINDOWS:
        if hasattr(fd, "setblocking"):
            fd.setblocking(False)
        else:
            os.set_blocking(fd, False)
        return
    flags = fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK
    fcntl.fcntl(fd, fcntl.F_SETFL, flags)
