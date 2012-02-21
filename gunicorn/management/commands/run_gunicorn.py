# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from optparse import make_option
import sys

from django.core.management.base import BaseCommand, CommandError

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
        if k in ('pythonpath', 'django_settings',):
            continue

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
            raise CommandError('Usage is run_gunicorn %s' % self.args)

        if addrport:
            options['bind'] = addrport

        admin_media_path = options.pop('admin_media_path', '')
        DjangoApplicationCommand(options, admin_media_path).run()
