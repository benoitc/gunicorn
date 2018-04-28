import sys

from gunicorn import six


def _check_if_pyc(fname):
    """Return True if the extension is .pyc, False if .py
    and None if otherwise"""
    from imp import find_module
    from os.path import realpath, dirname, basename, splitext

    # Normalize the file-path for the find_module()
    filepath = realpath(fname)
    dirpath = dirname(filepath)
    module_name = splitext(basename(filepath))[0]

    # Validate and fetch
    try:
        fileobj, fullpath, (_, _, pytype) = find_module(module_name, [dirpath])
    except ImportError:
        raise IOError("Cannot find config file. "
                      "Path maybe incorrect! : {}".format(filepath))
    return pytype, fileobj, fullpath


def _get_codeobj(pyfile):
    """ Returns the code object, given a python file """
    from imp import PY_COMPILED, PY_SOURCE

    result, fileobj, fullpath = _check_if_pyc(pyfile)

    # WARNING:
    # fp.read() can blowup if the module is extremely large file.
    # Lookout for overflow errors.
    try:
        data = fileobj.read()
    finally:
        fileobj.close()

    # This is a .pyc file. Treat accordingly.
    if result is PY_COMPILED:
        # .pyc format is as follows:
        # 0 - 4 bytes: Magic number, which changes with each create of .pyc file.
        #              First 2 bytes change with each marshal of .pyc file. Last 2 bytes is "\r\n".
        # 4 - 8 bytes: Datetime value, when the .py was last changed.
        # 8 - EOF: Marshalled code object data.
        # So to get code object, just read the 8th byte onwards till EOF, and
        # UN-marshal it.
        import marshal
        code_obj = marshal.loads(data[8:])

    elif result is PY_SOURCE:
        # This is a .py file.
        code_obj = compile(data, fullpath, 'exec')

    else:
        # Unsupported extension
        raise Exception("Input file is unknown format: {}".format(fullpath))

    # Return code object
    return code_obj

def execfile_(fname, *args):
    if fname.endswith(".pyc"):
        code = _get_codeobj(fname)
    else:
        code = compile(open(fname, 'rb').read(), fname, 'exec')
    return six.exec_(code, *args)

def bytes_to_str(b):
    if isinstance(b, six.text_type):
        return b
    return str(b, 'latin1')

import urllib.parse

def unquote_to_wsgi_str(string):
    return _unquote_to_bytes(string).decode('latin-1')

_unquote_to_bytes = urllib.parse.unquote_to_bytes


# The following code adapted from trollius.py33_exceptions
def _wrap_error(exc, mapping, key):
    if key not in mapping:
        return
    new_err_cls = mapping[key]
    new_err = new_err_cls(*exc.args)

    # raise a new exception with the original traceback
    six.reraise(new_err_cls, new_err,
                exc.__traceback__ if hasattr(exc, '__traceback__') else sys.exc_info()[2])

import builtins

BlockingIOError = builtins.BlockingIOError
BrokenPipeError = builtins.BrokenPipeError
ChildProcessError = builtins.ChildProcessError
ConnectionRefusedError = builtins.ConnectionRefusedError
ConnectionResetError = builtins.ConnectionResetError
InterruptedError = builtins.InterruptedError
ConnectionAbortedError = builtins.ConnectionAbortedError
PermissionError = builtins.PermissionError
FileNotFoundError = builtins.FileNotFoundError
ProcessLookupError = builtins.ProcessLookupError

def wrap_error(func, *args, **kw):
    return func(*args, **kw)


import inspect

positionals = (
    inspect.Parameter.POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD,
)

def get_arity(f):
    sig = inspect.signature(f)
    arity = 0

    for param in sig.parameters.values():
        if param.kind in positionals:
            arity += 1

    return arity
