# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import os
import sys

from gunicorn import util
from gunicorn.app.base import Application


class WSGIApplication(Application):

    def init(self, parser, opts, args):
        if len(args) != 1:
            parser.error("No application module specified.")

        self.cfg.set("default_proc_name", args[0])
        self.app_uri = args[0]

        sys.path.insert(0, os.getcwd())

    def load(self):
        return util.import_app(self.app_uri)


def run():
    """\
    The ``gunicorn`` command line runner for launcing Gunicorn with
    generic WSGI applications.
    """
    from gunicorn.app.wsgiapp import WSGIApplication
    WSGIApplication("%(prog)s [OPTIONS] APP_MODULE").run()
