#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Async uWSGI protocol parser for ASGI workers.

Reuses the parsing logic from gunicorn/uwsgi/message.py, only async I/O differs.
"""

from gunicorn.uwsgi.message import UWSGIRequest
from gunicorn.uwsgi.errors import (
    InvalidUWSGIHeader,
    UnsupportedModifier,
)


class AsyncUWSGIRequest(UWSGIRequest):
    """Async version of UWSGIRequest.

    Reuses all parsing logic from the sync version, only async I/O differs.
    The following methods are reused from the parent class:
    - _parse_vars() - pure parsing, no I/O
    - _extract_request_info() - pure transformation
    - _check_allowed_ip() - no I/O
    - should_close() - simple logic
    """

    # pylint: disable=super-init-not-called
    def __init__(self, cfg, unreader, peer_addr, req_number=1):
        # Don't call super().__init__ - it does sync parsing
        # Just initialize attributes
        self.cfg = cfg
        self.unreader = unreader
        self.peer_addr = peer_addr
        self.remote_addr = peer_addr
        self.req_number = req_number

        # Initialize all attributes (same as sync version)
        self.method = None
        self.uri = None
        self.path = None
        self.query = None
        self.fragment = ""
        self.version = (1, 1)
        self.headers = []
        self.trailers = []
        self.body = None
        self.scheme = "https" if cfg.is_ssl else "http"
        self.must_close = False
        self.uwsgi_vars = {}
        self.modifier1 = 0
        self.modifier2 = 0
        self.proxy_protocol_info = None

        # Body state
        self.content_length = 0
        self.chunked = False
        self._body_remaining = 0

    # Async factory method - intentionally differs from sync parent:
    # - async instead of sync (invalid-overridden-method)
    # - different signature for async I/O (arguments-differ)
    # pylint: disable=arguments-differ,invalid-overridden-method
    @classmethod
    async def parse(cls, cfg, unreader, peer_addr, req_number=1):
        """Parse a uWSGI request asynchronously.

        Args:
            cfg: gunicorn config object
            unreader: AsyncUnreader instance
            peer_addr: client address tuple
            req_number: request number on this connection (for keepalive)

        Returns:
            AsyncUWSGIRequest: Parsed request object

        Raises:
            InvalidUWSGIHeader: If the uWSGI header is malformed
            UnsupportedModifier: If modifier1 is not 0
            ForbiddenUWSGIRequest: If source IP is not allowed
        """
        req = cls(cfg, unreader, peer_addr, req_number)
        req._check_allowed_ip()  # Reuse from parent
        await req._async_parse()
        return req

    async def _async_parse(self):
        """Async version of parse() - reads data then uses sync parsing."""
        # Read 4-byte header
        header = await self._async_read_exact(4)
        if len(header) < 4:
            raise InvalidUWSGIHeader("incomplete header")

        self.modifier1 = header[0]
        datasize = int.from_bytes(header[1:3], 'little')
        self.modifier2 = header[3]

        if self.modifier1 != 0:
            raise UnsupportedModifier(self.modifier1)

        # Read vars block
        if datasize > 0:
            vars_data = await self._async_read_exact(datasize)
            if len(vars_data) < datasize:
                raise InvalidUWSGIHeader("incomplete vars block")
            self._parse_vars(vars_data)  # Reuse sync method

        self._extract_request_info()  # Reuse sync method
        self._set_body_reader()

    async def _async_read_exact(self, size):
        """Read exactly size bytes asynchronously."""
        buf = bytearray()
        while len(buf) < size:
            chunk = await self.unreader.read(size - len(buf))
            if not chunk:
                break
            buf.extend(chunk)
        return bytes(buf)

    def _set_body_reader(self):
        """Set up body state for async reading."""
        content_length = 0
        if 'CONTENT_LENGTH' in self.uwsgi_vars:
            try:
                content_length = max(int(self.uwsgi_vars['CONTENT_LENGTH']), 0)
            except ValueError:
                content_length = 0
        self.content_length = content_length
        self._body_remaining = content_length

    async def read_body(self, size=8192):
        """Read body chunk asynchronously.

        Args:
            size: Maximum bytes to read

        Returns:
            bytes: Body data, empty bytes when body is exhausted
        """
        if self._body_remaining <= 0:
            return b""
        to_read = min(size, self._body_remaining)
        data = await self.unreader.read(to_read)
        if data:
            self._body_remaining -= len(data)
        return data

    async def drain_body(self):
        """Drain unread body data.

        Should be called before reusing connection for keepalive.
        """
        while self._body_remaining > 0:
            data = await self.read_body(8192)
            if not data:
                break

    def get_header(self, name):
        """Get header by name (case-insensitive).

        Args:
            name: Header name to look up

        Returns:
            Header value if found, None otherwise
        """
        name = name.upper()
        for h, v in self.headers:
            if h == name:
                return v
        return None
