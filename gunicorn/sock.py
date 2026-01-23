#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import errno
import os
import socket
import ssl
import stat
import sys
import time

from gunicorn import util

PLATFORM = sys.platform


if PLATFORM == "linux":
    def get_backlog(sock):
        return -1
else:
    import struct
    # tcp_info struct from include/uapi/linux/tcp.h
    _TCPI_FMT = 'B' * 8 + 'I' * 24
    _TCPI_INDEX_UNACKED = 12
    def get_backlog(sock):
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            return -1
        try:
            tcp_info_struct = self.sock.getsockopt(socket.IPPROTO_TCP,
                                                   socket.TCP_INFO, 104)
            return struct.unpack(_TCPI_FMT, tcp_info_struct)[_TCPI_INDEX_UNACKED]
        except (AttributeError, OSError):
            pass
        return 0


def _get_socket_family(addr):
    if isinstance(addr, tuple):
        if util.is_ipv6(addr[0]):
            return socket.AF_INET6
        else:
            return socket.AF_INET

    if isinstance(addr, (str, bytes)):
        return socket.AF_UNIX

    raise TypeError("Unable to determine socket family for: %r" % addr)


def create_socket(conf, log, addr):
    family = _get_socket_family(addr)

    if family is socket.AF_UNIX:
        # remove any existing socket at the given path
        try:
            st = os.stat(addr)
        except OSError as err:
            if err.args[0] != errno.ENOENT:
                raise
        else:
            if stat.S_ISSOCK(st.st_mode):
                os.remove(addr)
            else:
                raise ValueError("%r already exists but is not a UNIX socket" % addr)

    for i in range(5):
        try:
            sock = socket.socket(family)
            sock.bind(addr)
            sock.listen(conf.backlog)
            if family is socket.AF_UNIX:
                util.chown(addr, conf.uid, conf.gid)
            return sock
        except OSError as e:
            if e.errno == errno.EADDRINUSE:
                log.error("Connection in use: %s", str(addr))
            if e.errno == errno.EADDRNOTAVAIL:
                log.error("Invalid address: %s", str(addr))
            msg = "connection to {addr} failed: {error}"
            log.error(msg.format(addr=str(addr), error=str(e)))
            if i < 5:
                log.debug("Retrying in 1 second.")
                time.sleep(1)

    log.error("Can't connect to %s", str(addr))
    sys.exit(1)


def create_sockets(conf, log, fds=None):
    """
    Create a new socket for the configured addresses or file descriptors.

    If a configured address is a tuple then a TCP socket is created.
    If it is a string, a Unix socket is created. Otherwise, a TypeError is
    raised.
    """
    listeners = []

    # get it only once
    addr = conf.address
    fdaddr = [bind for bind in addr if isinstance(bind, int)]
    if fds:
        fdaddr += list(fds)
    laddr = [bind for bind in addr if not isinstance(bind, int)]

    # check ssl config early to raise the error on startup
    # only the certfile is needed since it can contains the keyfile
    if conf.certfile and not os.path.exists(conf.certfile):
        raise ValueError('certfile "%s" does not exist' % conf.certfile)

    if conf.keyfile and not os.path.exists(conf.keyfile):
        raise ValueError('keyfile "%s" does not exist' % conf.keyfile)

    # sockets are already bound
    if fdaddr:
        for fd in fdaddr:
            # no file descriptor duplication
            sock = socket.socket(fileno=fd)
            set_socket_options(conf, sock)
            listeners.append(sock)
        return listeners

    # no sockets is bound, first initialization of gunicorn in this env.
    old_umask = os.umask(conf.umask)
    try:
        bind_list = [bind for bind in conf.address if not isinstance(bind, int)]
        for addr in laddr:
            sock = create_socket(conf, log, addr)
            set_socket_options(conf, sock)
            listeners.append(sock)
    finally:
        os.umask(old_umask)

    return listeners


def close_sockets(listeners, unlink=True):
    for sock in listeners:
        try:
            if unlink and sock.family is socket.AF_UNIX:
                sock_name = sock.getsockname()
                os.unlink(sock_name)
        finally:
            sock.close()


def get_uri(listener, is_ssl):
    addr = listener.getsockname()
    family = _get_socket_family(addr)
    scheme = "https" if is_ssl else "http"

    if family is socket.AF_INET:
        (host, port) = listener.getsockname()
        return f"{scheme}://{host}:{port}"

    if family is socket.AF_INET6:
        (host, port, _, _) = listener.getsockname()
        return f"{scheme}://[{host}]:{port}"

    if family is socket.AF_UNIX:
        path = listener.getsockname()
        return f"unix://{path}"


def set_socket_options(conf, sock):
    sock.setblocking(False)

    # make sure that the socket can be inherited
    if hasattr(sock, "set_inheritable"):
        sock.set_inheritable(True)

    if sock.family in (socket.AF_INET, socket.AF_INET6):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if (conf.reuse_port and hasattr(socket, 'SO_REUSEPORT')):  # pragma: no cover
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError as err:
                if err.errno not in (errno.ENOPROTOOPT, errno.EINVAL):
                    raise


def ssl_context(conf):
    def default_ssl_context_factory():
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH, cafile=conf.ca_certs)
        context.load_cert_chain(certfile=conf.certfile, keyfile=conf.keyfile)
        context.verify_mode = conf.cert_reqs
        if conf.ciphers:
            context.set_ciphers(conf.ciphers)
        return context

    return conf.ssl_context(conf, default_ssl_context_factory)


def ssl_wrap_socket(sock, conf):
    return ssl_context(conf).wrap_socket(sock,
                                         server_side=True,
                                         suppress_ragged_eofs=conf.suppress_ragged_eofs,
                                         do_handshake_on_connect=conf.do_handshake_on_connect)
