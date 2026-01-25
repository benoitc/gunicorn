#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from gunicorn.http.parser import Parser
from gunicorn.fastcgi.message import FastCGIRequest


class FastCGIParser(Parser):
    """Parser for FastCGI protocol requests."""

    mesg_class = FastCGIRequest
