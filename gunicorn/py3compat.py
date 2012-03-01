import sys

PY3 = sys.version_info[0] == 3

if PY3:
    string_types = str,
    integer_types = int,
    text_type = str

    import io
    StringIO = io.StringIO

else:
    string_types = basestring,
    integer_types = (int, long)
    text_type = unicode

    try:
        import cStringIO
        StringIO = cStringIO.StringIO
    except ImportError:
        import StringIO
        StringIO = StringIO.StringIO

