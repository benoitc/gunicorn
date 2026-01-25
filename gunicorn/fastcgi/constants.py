#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""FastCGI protocol constants.

Based on the FastCGI Specification:
https://fastcgi-archives.github.io/FastCGI_Specification.html
"""

# Protocol version
FCGI_VERSION_1 = 1

# Record types
FCGI_BEGIN_REQUEST = 1
FCGI_ABORT_REQUEST = 2
FCGI_END_REQUEST = 3
FCGI_PARAMS = 4
FCGI_STDIN = 5
FCGI_STDOUT = 6
FCGI_STDERR = 7
FCGI_DATA = 8
FCGI_GET_VALUES = 9
FCGI_GET_VALUES_RESULT = 10
FCGI_UNKNOWN_TYPE = 11

# Roles (in BEGIN_REQUEST)
FCGI_RESPONDER = 1
FCGI_AUTHORIZER = 2
FCGI_FILTER = 3

# Flags (in BEGIN_REQUEST)
FCGI_KEEP_CONN = 1

# Protocol status (in END_REQUEST)
FCGI_REQUEST_COMPLETE = 0
FCGI_CANT_MPX_CONN = 1
FCGI_OVERLOADED = 2
FCGI_UNKNOWN_ROLE = 3

# Header size (8 bytes fixed)
FCGI_HEADER_LEN = 8

# Maximum content length per record (64KB - 1)
FCGI_MAX_CONTENT_LEN = 65535

# Maximum number of parameters to prevent DoS
MAX_FCGI_PARAMS = 1000

# Null request ID (for management records)
FCGI_NULL_REQUEST_ID = 0

# Record type names for debugging
FCGI_RECORD_TYPES = {
    FCGI_BEGIN_REQUEST: 'BEGIN_REQUEST',
    FCGI_ABORT_REQUEST: 'ABORT_REQUEST',
    FCGI_END_REQUEST: 'END_REQUEST',
    FCGI_PARAMS: 'PARAMS',
    FCGI_STDIN: 'STDIN',
    FCGI_STDOUT: 'STDOUT',
    FCGI_STDERR: 'STDERR',
    FCGI_DATA: 'DATA',
    FCGI_GET_VALUES: 'GET_VALUES',
    FCGI_GET_VALUES_RESULT: 'GET_VALUES_RESULT',
    FCGI_UNKNOWN_TYPE: 'UNKNOWN_TYPE',
}
