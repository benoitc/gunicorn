#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from gunicorn.http.parser import Parser
from gunicorn.uwsgi.message import UWSGIRequest


class UWSGIParser(Parser):
    """Parser for uWSGI protocol requests."""

    mesg_class = UWSGIRequest
