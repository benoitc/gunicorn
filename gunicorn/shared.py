
try:
    from .sharedctypes import Value
    ctypes = True
except ImportError:
    ctypes = False
import threading

if not ctypes:

    import mmap
    import struct

    class Value(object):

        def __init__(self, fmt, val):
            self.struct = struct.Struct(fmt)
            self._buffer = mmap.mmap(-1, mmap.PAGESIZE)
            self._val = val
            self._commit()

        def _commit(self):
            s = self.struct.pack(self._val)
            self._buffer.seek(0)
            self._buffer.write(s)

        @property
        def value(self):
            self._buffer.seek(0)
            print self._buffer.size
            v, = self.struct.unpack(self._buffer[:self._buffer.size()])
            return v

        @value.setter
        def value(self, new):
            self._val = new
            self._commit()
