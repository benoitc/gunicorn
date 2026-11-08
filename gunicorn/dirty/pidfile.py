#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""PID file of the dirty arbiter.

The file lives at a well-known path in the temporary directory so a new
master can find and stop a dirty arbiter left behind by a crash. That
directory is shared, so the file is only trusted when this user created it:
a file planted by another user must never make gunicorn signal a process.
"""

import os
import stat


def _owned_regular_file(st):
    """A regular file owned by this user that nobody else can write."""
    return (stat.S_ISREG(st.st_mode)
            and st.st_uid == os.geteuid()
            and not st.st_mode & (stat.S_IWGRP | stat.S_IWOTH))


def write_pidfile(path, pid):
    """Write ``pid`` to ``path``, created by this user with mode 0600.

    A stale file this user owns is replaced. A file owned by someone else, or
    a symlink, is left alone and the PID is not written. Returns True when the
    file was written.
    """
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        pass
    else:
        if not _owned_regular_file(st):
            return False
        os.unlink(path)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(str(pid))
    return True


def process_owned_by_us(pid):
    """False when the process is gone or belongs to another user.

    Uses /proc on Linux.

    Where /proc is not available, os.kill() itself refuses to signal another
    user's process unless gunicorn runs as root, and read_trusted_pid()
    already requires the file to be ours.
    """
    try:
        return os.stat("/proc/%d" % pid).st_uid == os.geteuid()
    except FileNotFoundError:
        return not os.path.isdir("/proc/self")
    except OSError:
        return False


def read_trusted_pid(path):
    """Return the PID stored in ``path`` if the file can be trusted, else None.

    Trusted means: a regular file (not a symlink) owned by this user, not
    writable by group or others, holding a positive integer other than our
    own PID. Whether that process still exists, and is ours, is checked by
    the caller with process_owned_by_us().
    """
    try:
        st = os.lstat(path)
    except OSError:
        return None
    if not _owned_regular_file(st):
        return None

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    with os.fdopen(fd) as f:
        try:
            pid = int(f.read(32).strip())
        except ValueError:
            return None
    if pid <= 0 or pid == os.getpid():
        return None
    return pid
