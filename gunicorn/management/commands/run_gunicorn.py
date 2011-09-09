# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from optparse import make_option
import sys

 
import django
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.utils import translation

from gunicorn.app.djangoapp import DjangoApplicationCommand
from gunicorn.config import make_settings

def make_options():
    g_settings = make_settings(ignore=("version"))

    keys = g_settings.keys()
    def sorter(k):
        return (g_settings[k].section, g_settings[k].order)

    opts = [
        make_option('--adminmedia', dest='admin_media_path', default='',
        help='Specifies the directory from which to serve admin media.')
    ]

    for k in keys:
        setting = g_settings[k]
        if not setting.cli:
            continue

        args = tuple(setting.cli)

        kwargs = {
            "dest": setting.name,
            "metavar": setting.meta or None,
            "action": setting.action or "store",
            "type": setting.type or "string",
            "default": None,
            "help": "%s [%s]" % (setting.short, setting.default)
        }
        if kwargs["action"] != "store":
            kwargs.pop("type")

        opts.append(make_option(*args, **kwargs))

    return tuple(opts)

GUNICORN_OPTIONS = make_options()


class Command(BaseCommand):
    option_list = BaseCommand.option_list + GUNICORN_OPTIONS
    help = "Starts a fully-functional Web server using gunicorn."
    args = '[optional port number, or ipaddr:port or unix:/path/to/sockfile]'
 
    # Validation is called explicitly each time the server is reloaded.
    requires_model_validation = False
 
    def handle(self, addrport=None, *args, **options):
        if args:
            raise CommandError('Usage is runserver %s' % self.args)
            
        if addrport:
            options['bind'] = addrport
        
        options['default_proc_name'] = settings.SETTINGS_MODULE

        admin_media_path = options.pop('admin_media_path', '')
        quit_command = (sys.platform == 'win32') and 'CTRL-BREAK' or 'CONTROL-C'

        print "Validating models..."
        self.validate(display_num_errors=True)
        print "\nDjango version %s, using settings %r" % (django.get_version(), 
                                            settings.SETTINGS_MODULE)
        print "Server is running"
        print "Quit the server with %s." % quit_command
 
        # django.core.management.base forces the locale to en-us.
        translation.activate(settings.LANGUAGE_CODE)
        DjangoApplicationCommand(options, admin_media_path).run()
