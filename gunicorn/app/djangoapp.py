# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import imp
import logging
import os
import sys
import time
import traceback
import re

from gunicorn.config import Config
from gunicorn.app.base import Application

class DjangoApplication(Application):

    def init(self, parser, opts, args):
        if len(args) > 1:
            parser.error("Expected zero or one arguments, got %s" % len(args))
        self.project_dir = None
        if args:
            self.project_dir = args.pop()
        self.settings_modname = self.find_settings()[0]
        self.cfg.set("default_proc_name", self.settings_modname)
           
    def find_settings(self):
        from django.conf import ENVIRONMENT_VARIABLE

        # get settings module
        settings_modname = None
        python_path = None
        project_dir = None
        if not self.project_dir:
            try:
                settings_modname = os.environ[ENVIRONMENT_VARIABLE]
            except KeyError:
                project_dir = os.path.abspath(os.getcwd())
        else:
            project_dir = os.path.abspath(self.project_dir)

        if not settings_modname:
            python_path = [os.path.normpath(os.path.join(
                project_dir, os.pardir))]
            project_name = os.path.basename(project_dir)
            print project_name, project_dir, python_path
            if not os.path.exists(os.path.join(project_dir, 'settings.py')):
                return self.no_settings('settings.py')
            settings_modname = "%s.%s" % (project_name, 'settings')
            os.environ[ENVIRONMENT_VARIABLE] = settings_modname

        return settings_modname, python_path

    def import_settings(self):
        # find the settings module
        settings_modname, python_path = self.find_settings()

        # import settings module
        try:
            imp.acquire_lock()
            module = None
            for part in self.settings_modname.split("."):
                name = part
                if module:
                    python_path = getattr(module, '__path__', None)
                    if not python_path: raise ImportError()
                    name = '.'.join([module.__name__, part])
                file, path, desc = imp.find_module(part, python_path)
                try:
                    module = imp.load_module(name, file, path, desc)
                finally:
                    if file: file.close()
        except ImportError:
            return self.no_settings(self.settings_modname, import_error=True)
        finally:
            imp.release_lock()

        return module

    def no_settings(self, path, import_error=False):
        if import_error:
            error = "Error: Can't find '%s' in your PYTHONPATH.\n" % path
        else:
            error = "Settings file '%s' not found in project folder.\n" % path
        sys.stderr.write(error)
        sys.stderr.flush()
        sys.exit(1)

    def activate_translation(self):
        from django.conf import settings
        from django.utils import translation
        translation.activate(settings.LANGUAGE_CODE)
        
    def validate(self):
        """ Validate models. This also ensures that all models are 
        imported in case of import-time side effects."""
        from django.core.management.base import CommandError
        from django.core.management.validation import get_validation_errors
        try:
            from cStringIO import StringIO
        except ImportError:
            from StringIO import StringIO

        s = StringIO()
        if get_validation_errors(s):
            s.seek(0)
            error = s.read()
            sys.stderr.write("One or more models did not validate:\n%s" % error)
            sys.stderr.flush()

            sys.exit(1)

    @property
    def django_handler(self):
        try:
            from django.core.servers.basehttp import \
                 get_internal_wsgi_application
            return get_internal_wsgi_application
        except ImportError: # django < 1.4
            from django.core.handlers.wsgi import WSGIHandler
            return WSGIHandler

    def load(self):
        settings_module = self.import_settings()
        self.validate()
        self.activate_translation()

        return self.django_handler()

class DjangoApplicationCommand(DjangoApplication):
    
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
        self.init(None, None, [])

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
        
            for k, v in cfg.items():
                # Ignore unknown names
                if k not in self.cfg.settings:
                    continue
                try:
                    self.cfg.set(k.lower(), v)
                except:
                    sys.stderr.write("Invalid value for %s: %s\n\n" % (k, v))
                    raise
       
        for k, v in self.options.items():
            if k.lower() in self.cfg.settings and v is not None:
                self.cfg.set(k.lower(), v)

    def import_settings(self):
        from django.conf import settings
        from django.utils import importlib

        # reload module
        mod = super(DjangoApplicationCommand, self).import_settings()

        # reload settings.
        # USe code from django.settings.Settings module.

        # Settings that should be converted into tuples if they're mistakenly entered
        # as strings.
        tuple_settings = ("INSTALLED_APPS", "TEMPLATE_DIRS")

        for setting in dir(mod):
            if setting == setting.upper():
                setting_value = getattr(mod, setting)
                if setting in tuple_settings and type(setting_value) == str:
                    setting_value = (setting_value,) # In case the user forgot the comma.
                setattr(settings, setting, setting_value)

        # Expand entries in INSTALLED_APPS like "django.contrib.*" to a list
        # of all those apps.
        new_installed_apps = []
        for app in settings.INSTALLED_APPS:
            if app.endswith('.*'):
                app_mod = importlib.import_module(app[:-2])
                appdir = os.path.dirname(app_mod.__file__)
                app_subdirs = os.listdir(appdir)
                app_subdirs.sort()
                name_pattern = re.compile(r'[a-zA-Z]\w*')
                for d in app_subdirs:
                    if name_pattern.match(d) and os.path.isdir(os.path.join(appdir, d)):
                        new_installed_apps.append('%s.%s' % (app[:-2], d))
            else:
                new_installed_apps.append(app)
        setattr(settings, "INSTALLED_APPS", new_installed_apps)

        if hasattr(time, 'tzset') and settings.TIME_ZONE:
            # When we can, attempt to validate the timezone. If we can't find
            # this file, no check happens and it's harmless.
            zoneinfo_root = '/usr/share/zoneinfo'
            if (os.path.exists(zoneinfo_root) and not
                    os.path.exists(os.path.join(zoneinfo_root,
                        *(settings.TIME_ZONE.split('/'))))):
                raise ValueError("Incorrect timezone setting: %s" %
                        settings.TIME_ZONE)
            # Move the time zone info into os.environ. See ticket #2315 for why
            # we don't do this unconditionally (breaks Windows).
            os.environ['TZ'] = settings.TIME_ZONE
            time.tzset()

        # Settings are configured, so we can set up the logger if required
        if getattr(settings, 'LOGGING_CONFIG', False):
            # First find the logging configuration function ...
            logging_config_path, logging_config_func_name = settings.LOGGING_CONFIG.rsplit('.', 1)
            logging_config_module = importlib.import_module(logging_config_path)
            logging_config_func = getattr(logging_config_module, logging_config_func_name)

            # ... then invoke it with the logging settings
            logging_config_func(settings.LOGGING)

        return mod

    def load(self):
        from django.core.servers.basehttp import AdminMediaHandler
        return AdminMediaHandler(self.django_handler(), self.admin_media_path)
           
def run():
    """\
    The ``gunicorn_django`` command line runner for launching Django
    applications.
    """
    from gunicorn.app.djangoapp import DjangoApplication
    DjangoApplication("%prog [OPTIONS] [PROJECT_DIR]").run()
