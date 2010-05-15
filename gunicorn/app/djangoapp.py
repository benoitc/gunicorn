# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import os
import sys

import django.core.handlers.wsgi

from gunicorn import util
from gunicorn.app.base import Application

class DjangoApplication(Application):
    
    def init(parser, opts, args):
        self.project_path = os.getcwd()
    
        if args:
            settings_path = os.path.abspath(os.path.normpath(args[0]))
            if not os.path.exists(settings_path):
                self.no_settings(settings_path)
            else:
                self.project_path = os.path.dirname(settings_path)
        else:
             settings_path = os.path.join(project_path, "settings.py")
             if not os.path.exists(settings_path):
                 self.no_settings(settings_path)

        project_name = os.path.split(project_path)[-1]
        settings_name, ext  = os.path.splitext(os.path.basename(settings_path))
        settings_modname = "%s.%s" % (project_name, settings_name)
        self.cfg.default_proc_name  = settings_modname

        sys.path.insert(0, self.project_path)
        sys.path.append(os.path.join(project_path, os.pardir))

    def no_settings(self, path):
        error = "Settings file '%s' not found in current folder.\n" % path
        sys.stderr.write(error)
        sys.stderr.flush()
        sys.exit(1)
        
    def load(self):
        os.environ['DJANGO_SETTINGS_MODULE'] = self.settings_modname
        return django.core.handlers.wsgi.WSGIHandler()
