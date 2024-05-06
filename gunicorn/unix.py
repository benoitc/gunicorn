import fcntl
import grp
import os
import pwd


def resolve_uid(val):
    return pwd.getpwnam(val).pw_uid


def resolve_gid(val):
    return grp.getgrnam(val).gr_gid


def _assert_cloexec(fd):
    # Python 3.4+: file descriptors created by Python non-inheritable by default
    fd_flags = fcntl.fcntl(fd, fcntl.F_GETFD)
    # mind the difference between os.O_CLOEXEC and fcntl.FD_CLOEXEC
    if not fd_flags | fcntl.FD_CLOEXEC:
        raise AssertionError("Expected FD_CLOEXEC set on fd %r" % fd)


def _assert_nonblock(fd):
    # mind the difference between F_GETFD and F_GETFL
    fl_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    if not fl_flags | os.O_NONBLOCK:
        raise AssertionError("Expected O_NONBLOCK set on fd %r" % fd)


if hasattr(os, "pipe2"):
    # atomic
    def pipe2():
        read, write = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        for fd in (read, write):
            _assert_cloexec(fd)
            _assert_nonblock(fd)
        return read, write

    close_on_exec = _assert_cloexec
else:

    def close_on_exec(fd):
        flags = fcntl.fcntl(fd, fcntl.F_GETFD)
        flags |= fcntl.FD_CLOEXEC
        fcntl.fcntl(fd, fcntl.F_SETFD, flags)

    def _set_non_blocking(fd):
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        flags |= os.O_NONBLOCK
        fcntl.fcntl(fd, fcntl.F_SETFL, flags)

    def pipe2():
        # race condition
        read_write = os.pipe()
        for fd in read_write:
            _set_non_blocking(fd)
            close_on_exec(fd)
        return read_write


def _get_username(uid):
    """get the username for a user id"""
    return pwd.getpwuid(uid).pw_name


def _drop_supplemental_groups():
    # only root/CAP_SETGID can do this
    try:
        os.setgroups([])
    except OSError as ex:
        if ex.errno != errno.EPERM:
            raise


def matching_effective_uid_gid(uid, gid):
    return uid == os.geteuid() and gid == os.getegid()


def set_owner_process(uid, gid, initgroups=False):
    """set user and group of workers processes"""

    # note: uid/gid can be larger than 2**32
    # note: setgid() does not empty supplemental group list
    # note: will never act on uid=0 / gid=0

    if gid:
        if uid:
            try:
                username = _get_username(uid)
            except KeyError:
                initgroups = False

        if initgroups:
            os.initgroups(username, gid)
        elif gid != os.getgid():
            os.setgid(gid)
            _drop_supplemental_groups()

    if uid and uid != os.getuid():
        os.setuid(uid)


ALL = [
    "close_on_exec",
    "matching_effective_uid_gid",
    "pipe2",
    "resolve_gid",
    "resolve_uid",
    "set_owner_process",
]
