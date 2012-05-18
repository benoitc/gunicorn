import sys

PY3 = sys.version_info[0] == 3

if PY3:
    string_types = str,
    integer_types = int,
    text_type = str

    def b2s(s):
        return s.decode('latin1')

    def s2b(s):
        return s.encode('latin1')

    import io
    StringIO = io.StringIO
    BytesIO = io.BytesIO

    def raise_with_tb(E, V, T):
        raise E(V).with_traceback(T)

    MAXSIZE = sys.maxsize


else:
    string_types = basestring,
    integer_types = (int, long)
    text_type = unicode

    def b2s(s):
        return s

    def s2b(s):
        return s

    try:
        import cStringIO
        StringIO = cStringIO.StringIO
    except ImportError:
        import StringIO
        StringIO = StringIO.StringIO

    BytesIO = StringIO

    def raise_with_tb(E, V, T):
        raiseE, V, T


    # It's possible to have sizeof(long) != sizeof(Py_ssize_t).
    class X(object):
        def __len__(self):
            return 1 << 31
    try:
        len(X())
    except OverflowError:
        # 32-bit
        MAXSIZE = int((1 << 31) - 1)
    else:
        # 64-bit
        MAXSIZE = int((1 << 63) - 1)
    del X

