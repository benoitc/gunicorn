#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Cleartext HTTP/2 (h2c) negotiation, shared by every worker.

The I/O differs per worker: gthread and gevent read from a socket, the ASGI
worker is handed bytes by asyncio. The decisions do not. Keeping the pure,
I/O-free part here stops the blocking and push-based paths from drifting apart.
"""

import time

from gunicorn.http.message import _ip_in_allow_list

#: HTTP/2 connection preface sent by clients using prior knowledge,
#: RFC 9113 section 3.4.
H2C_PREFACE = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"

#: How long to wait for the whole preface once the first bytes arrive. This
#: is a budget for the entire preface, not per read.
H2C_PREFACE_TIMEOUT = 1.0

MATCH = "match"
PARTIAL = "partial"
MISMATCH = "mismatch"


def preface_match(buf):
    """Compare buffered bytes against the connection preface.

    Returns ``MATCH`` when the whole preface is present, ``PARTIAL`` when the
    bytes so far are a prefix of it and more could still arrive, and
    ``MISMATCH`` as soon as a byte diverges. Never blocks and never reads.
    """
    if len(buf) >= len(H2C_PREFACE):
        return MATCH if buf.startswith(H2C_PREFACE) else MISMATCH
    return PARTIAL if H2C_PREFACE.startswith(buf) else MISMATCH


def peer_trusted_for_h2c(cfg, peer_addr):
    """Whether this peer may negotiate cleartext HTTP/2.

    Reuses the ``forwarded_allow_ips`` trust list: h2c is only ever expected
    from the TLS-terminating proxy in front of gunicorn, which is the same
    peer already trusted to set forwarded headers. Unix socket peers are
    trusted, matching that policy.
    """
    if not isinstance(peer_addr, tuple):
        return True
    return _ip_in_allow_list(
        peer_addr[0], cfg.forwarded_allow_ips, cfg.forwarded_allow_networks()
    )


def _h2c_available(cfg):
    """Whether cleartext HTTP/2 could apply to this server at all."""
    return (
        "h2" in cfg.http_protocols
        and getattr(cfg, "protocol", "http") == "http"
        and not cfg.is_ssl
    )


def prior_knowledge_allowed(cfg, peer_addr):
    """Whether to sniff for the connection preface from this peer.

    Deliberately separate from :func:`upgrade_allowed`: enabling one mechanism
    must not quietly enable the other.
    """
    if cfg.http2_cleartext not in ("prior-knowledge", "both"):
        return False
    return _h2c_available(cfg) and peer_trusted_for_h2c(cfg, peer_addr)


def mismatch_is_error(cfg):
    """Whether a trusted peer failing to send the preface is a 400.

    Only when prior knowledge is the sole mechanism: such a peer is expected
    to speak HTTP/2 and a silent downgrade would hide a misconfiguration.
    When upgrade is also enabled, an HTTP/1 request is not a mistake, it is
    how an upgrade begins, so it has to be allowed through.
    """
    return cfg.http2_cleartext == "prior-knowledge"


def upgrade_allowed(cfg, peer_addr):
    """Whether to honour an ``Upgrade: h2c`` request from this peer."""
    if cfg.http2_cleartext not in ("upgrade", "both"):
        return False
    return _h2c_available(cfg) and peer_trusted_for_h2c(cfg, peer_addr)


def read_preface_blocking(sock, timeout=None):
    """Read up to the length of the preface from a blocking socket.

    Returns ``(matched, consumed_bytes)``. The caller owns the consumed bytes
    and must hand them to whichever protocol wins, since they have already
    left the socket.

    The timeout is an absolute budget for the whole preface, checked before
    every read. ``socket.settimeout()`` alone would bound each call instead,
    which lets a client trickle one byte per interval and hold the connection
    (and, on gthread, a pool slot) for as many intervals as the preface has
    bytes.
    """
    if timeout is None:
        # read at call time so the module attribute stays adjustable
        timeout = H2C_PREFACE_TIMEOUT
    buf = b""
    deadline = time.monotonic() + timeout
    original = sock.gettimeout()
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False, buf
            sock.settimeout(remaining)
            try:
                chunk = sock.recv(len(H2C_PREFACE) - len(buf))
            except (TimeoutError, OSError):
                return False, buf
            if not chunk:
                return False, buf
            buf += chunk
            state = preface_match(buf)
            if state is MATCH:
                return True, buf
            if state is MISMATCH:
                return False, buf
    finally:
        sock.settimeout(original)


#: Sent before switching an HTTP/1.1 connection over to HTTP/2.
UPGRADE_101 = (
    b"HTTP/1.1 101 Switching Protocols\r\n"
    b"Connection: Upgrade\r\n"
    b"Upgrade: h2c\r\n"
    b"\r\n"
)


def upgrade_settings(req):
    """Return the HTTP2-Settings payload if this request asks for h2c.

    RFC 7540 section 3.2: the request must name ``h2c`` in Upgrade and carry
    exactly one HTTP2-Settings header, itself named in Connection. Returns
    None when the request is not a well-formed upgrade attempt, so the caller
    simply carries on with HTTP/1.
    """
    upgrade = None
    settings = []
    connection = ""
    for name, value in req.headers:
        if name == "UPGRADE":
            upgrade = value.strip().lower()
        elif name == "HTTP2-SETTINGS":
            settings.append(value.strip())
        elif name == "CONNECTION":
            connection = value.lower()

    if upgrade != "h2c":
        return None
    # Exactly one, per RFC 7540 3.2.1: a second one is ambiguous.
    if len(settings) != 1:
        return None
    if "http2-settings" not in connection or "upgrade" not in connection:
        return None
    return settings[0].encode("latin-1")
