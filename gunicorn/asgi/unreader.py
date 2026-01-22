#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Async version of gunicorn/http/unreader.py for ASGI workers.

Provides async reading with pushback buffer support.
"""

import io


class AsyncUnreader:
    """Async socket reader with pushback buffer support.

    This class wraps an asyncio StreamReader and provides the ability
    to "unread" data back into a buffer for re-parsing.
    """

    def __init__(self, reader, max_chunk=8192):
        """Initialize the async unreader.

        Args:
            reader: asyncio.StreamReader instance
            max_chunk: Maximum bytes to read at once
        """
        self.reader = reader
        self.buf = io.BytesIO()
        self.max_chunk = max_chunk

    async def read(self, size=None):
        """Read data from the stream, using buffered data first.

        Args:
            size: Number of bytes to read. If None, returns all buffered
                  data or reads a single chunk.

        Returns:
            bytes: Data read from buffer or stream
        """
        if size is not None and not isinstance(size, int):
            raise TypeError("size parameter must be an int or long.")

        if size is not None:
            if size == 0:
                return b""
            if size < 0:
                size = None

        # Move to end to check buffer size
        self.buf.seek(0, io.SEEK_END)

        # If no size specified, return buffered data or read chunk
        if size is None and self.buf.tell():
            ret = self.buf.getvalue()
            self.buf = io.BytesIO()
            return ret
        if size is None:
            chunk = await self._read_chunk()
            return chunk

        # Read until we have enough data
        while self.buf.tell() < size:
            chunk = await self._read_chunk()
            if not chunk:
                ret = self.buf.getvalue()
                self.buf = io.BytesIO()
                return ret
            self.buf.write(chunk)

        data = self.buf.getvalue()
        self.buf = io.BytesIO()
        self.buf.write(data[size:])
        return data[:size]

    async def _read_chunk(self):
        """Read a chunk of data from the underlying stream."""
        try:
            return await self.reader.read(self.max_chunk)
        except Exception:
            return b""

    def unread(self, data):
        """Push data back into the buffer for re-reading.

        Args:
            data: bytes to push back
        """
        if data:
            self.buf.seek(0, io.SEEK_END)
            self.buf.write(data)

    def has_buffered_data(self):
        """Check if there's data in the pushback buffer."""
        pos = self.buf.tell()
        self.buf.seek(0, io.SEEK_END)
        has_data = self.buf.tell() > 0
        self.buf.seek(pos)
        return has_data
