import sys

PY3 = sys.version_info[0] == 3

if PY3:
    string_types = str,
    integer_types = int,
else:
    string_types = basestring,
    integer_types = (int, long)
