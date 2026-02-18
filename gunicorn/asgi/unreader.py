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

    Performance optimization: Reuses BytesIO buffer with truncate/seek
    instead of creating new objects to reduce GC pressure.
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
        self._buf_start = 0  # Start position of valid data in buffer

    def _reset_buffer(self):
        """Reset buffer for reuse instead of creating new BytesIO."""
        self.buf.seek(0)
        self.buf.truncate(0)
        self._buf_start = 0

    def _get_buffered_data(self):
        """Get all buffered data and reset buffer."""
        self.buf.seek(self._buf_start)
        data = self.buf.read()
        self._reset_buffer()
        return data

    def _buffer_size(self):
        """Get size of buffered data."""
        end = self.buf.seek(0, io.SEEK_END)
        return end - self._buf_start

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

        buf_size = self._buffer_size()

        # If no size specified, return buffered data or read chunk
        if size is None and buf_size > 0:
            return self._get_buffered_data()
        if size is None:
            chunk = await self._read_chunk()
            return chunk

        # Read until we have enough data
        while buf_size < size:
            chunk = await self._read_chunk()
            if not chunk:
                return self._get_buffered_data()
            self.buf.seek(0, io.SEEK_END)
            self.buf.write(chunk)
            buf_size += len(chunk)

        # We have enough data - extract what we need
        self.buf.seek(self._buf_start)
        data = self.buf.read(size)

        # Update start position instead of creating new buffer
        self._buf_start += size

        # If buffer is getting large with consumed data, compact it
        if self._buf_start > 8192:
            remaining = self.buf.read()  # Read from current position
            self._reset_buffer()
            if remaining:
                self.buf.write(remaining)

        return data

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

        Note: This prepends data to the buffer so it will be read first.
        """
        if data:
            # Get existing buffered data
            self.buf.seek(self._buf_start)
            existing = self.buf.read()

            # Reset and write new data first, then existing
            self._reset_buffer()
            self.buf.write(data)
            if existing:
                self.buf.write(existing)

    def has_buffered_data(self):
        """Check if there's data in the pushback buffer."""
        return self._buffer_size() > 0
