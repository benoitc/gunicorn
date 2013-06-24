# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import os
import sys

from gunicorn import util
from gunicorn.app.base import Application
from gunicorn.app import djangoapp


class WSGIApplication(Application):

    def init(self, parser, opts, args):
        if len(args) != 1:
            parser.error("No application module specified.")

        self.cfg.set("default_proc_name", args[0])
        self.app_uri = args[0]

        cwd = util.getcwd()

        sys.path.insert(0, cwd)

    def load(self):
        djangoapp.make_default_env(self.cfg)
        return util.import_app(self.app_uri)


def run():
    """\
    The ``gunicorn`` command line runner for launching Gunicorn with
    generic WSGI applications.
    """
    from gunicorn.app.wsgiapp import WSGIApplication
    WSGIApplication("%(prog)s [OPTIONS] APP_MODULE").run()


if __name__ == '__main__':
    run()
