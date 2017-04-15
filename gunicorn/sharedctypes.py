# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

try:
    import ctypes
    import ctypes.util
except MemoryError:
    # selinux execmem denial
    # https://bugzilla.redhat.com/show_bug.cgi?id=488396
    raise ImportError
import mmap
import sys
import _multiprocessing

from .six import PY3

fmt_to_ctype = {
    'c': ctypes.c_char,  'u': ctypes.c_wchar,
    'b': ctypes.c_byte,  'B': ctypes.c_ubyte,
    'h': ctypes.c_short, 'H': ctypes.c_ushort,
    'i': ctypes.c_int,   'I': ctypes.c_uint,
    'l': ctypes.c_long,  'L': ctypes.c_ulong,
    'f': ctypes.c_float, 'd': ctypes.c_double
    }

class Value(object):

    def __init__(self, code_or_ctype, val):
        type_ = fmt_to_ctype.get(code_or_ctype, code_or_ctype)
        print(type_)
        size = ctypes.sizeof(type_)
        self._mmap = mmap.mmap(-1, size)
        if '__pypy__' not in sys.builtin_module_names:
            self._val = type_.from_buffer(self._mmap)
        else:
            address, length = _multiprocessing.address_of_buffer(self._mmap)
            assert size <= length
            self._val = type_.from_address(address)

        ctypes.memset(ctypes.addressof(self._val), 0, ctypes.sizeof(self._val))

        # initialize the vallue
        self._val.value = val

    @property
    def value(self):
        return self._val.value

    @value.setter
    def value(self, new):
        self._val.value = new
