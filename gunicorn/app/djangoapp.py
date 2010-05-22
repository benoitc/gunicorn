# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import os
import sys

from django.core.handlers.wsgi import WSGIHandler
from django.core.servers.basehttp import AdminMediaHandler, WSGIServerException

from gunicorn.config import Config
from gunicorn.app.base import Application

class DjangoApplication(Application):
    
    def init(self, parser, opts, args):
        self.project_path = os.getcwd()
    
        if args:
            settings_path = os.path.abspath(os.path.normpath(args[0]))
            if not os.path.exists(settings_path):
                self.no_settings(settings_path)
            else:
                self.project_path = os.path.dirname(settings_path)
        else:
             settings_path = os.path.join(self.project_path, "settings.py")
             if not os.path.exists(settings_path):
                 self.no_settings(settings_path)

        project_name = os.path.split(self.project_path)[-1]
        settings_name, ext  = os.path.splitext(os.path.basename(settings_path))
        self.settings_modname = "%s.%s" % (project_name, settings_name)
        self.cfg.set("default_proc_name", self.settings_modname)

        sys.path.insert(0, self.project_path)
        sys.path.append(os.path.join(self.project_path, os.pardir))

    def no_settings(self, path):
        error = "Settings file '%s' not found in current folder.\n" % path
        sys.stderr.write(error)
        sys.stderr.flush()
        sys.exit(1)
        
    def load(self):
        os.environ['DJANGO_SETTINGS_MODULE'] = self.settings_modname
        return WSGIHandler()

class DjangoApplicationCommand(Application):
    
    def __init__(self, options, admin_media_path):
        self.cfg = Config()
        self.callable = None
        
        for k, v in list(options.items()):
            if k.lower() in self.cfg.settings and v is not None:
                self.cfg.set(k.lower(), v)
        
        self.admin_media_path = admin_media_path
        self.configure_logging()
        
    def load(self):
        try:
            return  AdminMediaHandler(WSGIHandler(), self.admin_media_path)
        except WSGIServerException, e:
            # Use helpful error messages instead of ugly tracebacks.
            ERRORS = {
                13: "You don't have permission to access that port.",
                98: "That port is already in use.",
                99: "That IP address can't be assigned-to.",
            }
            try:
                error_text = ERRORS[e.args[0].args[0]]
            except (AttributeError, KeyError):
                error_text = str(e)
            sys.stderr.write(self.style.ERROR("Error: %s" % error_text) + '\n')
            sys.exit(1)