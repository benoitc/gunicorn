# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import os
import sys
import traceback

from gunicorn.config import Config
from gunicorn.app.base import Application

class DjangoApplication(Application):
    
    def init(self, parser, opts, args):
        from django.conf import ENVIRONMENT_VARIABLE
        self.settings_modname = None
        self.project_path = os.getcwd()
        if args:
            settings_path = os.path.abspath(os.path.normpath(args[0]))
            if not os.path.exists(settings_path):
                self.no_settings(settings_path)
            else:
                self.project_path = os.path.dirname(settings_path)
        else:
            try:
                self.settings_modname = os.environ[ENVIRONMENT_VARIABLE]
            except KeyError:
                settings_path = os.path.join(self.project_path, "settings.py")
                if not os.path.exists(settings_path):
                    return self.no_settings(settings_path)

        if not self.settings_modname:
            project_name = os.path.split(self.project_path)[-1]
            settings_name, ext  = os.path.splitext(
                    os.path.basename(settings_path))
            self.settings_modname = "%s.%s" % (project_name, settings_name)
            os.environ[ENVIRONMENT_VARIABLE] = self.settings_modname
        
        self.cfg.set("default_proc_name", self.settings_modname)

        # add the project path to sys.path
        sys.path.insert(0, self.project_path)
        sys.path.append(os.path.join(self.project_path, os.pardir))

        # setup envoron
        self.setup_environ() 

    def setup_environ(self):
        from django.core.management import setup_environ
        try:
            parts = self.settings_modname.split(".")
            settings_mod = __import__(self.settings_modname)
            if len(parts) > 1:
                settings_mod = __import__(parts[0])
                path = os.path.dirname(os.path.abspath(
                            os.path.normpath(settings_mod.__file__)))
                sys.path.append(path)
                for part in parts[1:]: 
                    settings_mod = getattr(settings_mod, part)
                setup_environ(settings_mod)
        except ImportError:
            return self.no_settings(self.settings_modname, import_error=True)

    def no_settings(self, path, import_error=False):
        if import_error:
            error = "Error: Can't find the settings in your PYTHONPATH"
        else:
            error = "Settings file '%s' not found in current folder.\n" % path
        sys.stderr.write(error)
        sys.stderr.flush()
        sys.exit(1)
        
    def load(self):
        from django.conf import ENVIRONMENT_VARIABLE
        from django.core.handlers.wsgi import WSGIHandler
        os.environ[ENVIRONMENT_VARIABLE] = self.settings_modname
        return WSGIHandler()

class DjangoApplicationCommand(Application):
    
    def __init__(self, options, admin_media_path):
        self.usage = None
        self.cfg = None
        self.config_file = options.get("config") or ""
        self.options = options
        self.admin_media_path = admin_media_path
        self.callable = None
        self.do_load_config()

    def load_config(self):
        self.cfg = Config()
        
        if self.config_file and os.path.exists(self.config_file):
            cfg = {
                "__builtins__": __builtins__,
                "__name__": "__config__",
                "__file__": self.config_file,
                "__doc__": None,
                "__package__": None
            }
            try:
                execfile(self.config_file, cfg, cfg)
            except Exception:
                print "Failed to read config file: %s" % self.config_file
                traceback.print_exc()
                sys.exit(1)
        
            for k, v in list(cfg.items()):
                # Ignore unknown names
                if k not in self.cfg.settings:
                    continue
                try:
                    self.cfg.set(k.lower(), v)
                except:
                    sys.stderr.write("Invalid value for %s: %s\n\n" % (k, v))
                    raise
        
        for k, v in list(self.options.items()):
            if k.lower() in self.cfg.settings and v is not None:
                self.cfg.set(k.lower(), v)
        
    def load(self):
        from django.core.servers.basehttp import AdminMediaHandler, WSGIServerException
        from django.core.handlers.wsgi import WSGIHandler
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
            
def run():
    """\
    The ``gunicorn_django`` command line runner for launching Django
    applications.
    """
    from gunicorn.app.djangoapp import DjangoApplication
    DjangoApplication("%prog [OPTIONS] [SETTINGS_PATH]").run()
