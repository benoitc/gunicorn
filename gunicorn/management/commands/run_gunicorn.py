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
 
class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option('--adminmedia', dest='admin_media_path', default='',
            help='Specifies the directory from which to serve admin media.'),
        make_option('-c', '--config', dest='gconfig', type='string',
            help='Gunicorn Config file. [%default]'),
        make_option('-k', '--worker-class', dest='worker_class',
            help="The type of request processing to use "+
            "[egg:gunicorn#sync]"),
        make_option('-w', '--workers', dest='workers', 
            help='Specifies the number of worker processes to use.'),
        make_option('--pid', dest='pidfile',
            help='set the background PID file'),
        make_option( '--daemon', dest='daemon', action="store_true",
            help='Run daemonized in the background.'),
        make_option('--umask', dest='umask',
            help="Define umask of daemon process"),
        make_option('-u', '--user', dest="user", 
            help="Change worker user"),
        make_option('-g', '--group', dest="group", 
            help="Change worker group"),
        make_option('-n', '--name', dest='proc_name',
            help="Process name"),
        make_option('--preload', dest='preload_app', action='store_true', default=False,
            help="Load application code before the worker processes are forked.")
    )
    help = "Starts a fully-functional Web server using gunicorn."
    args = '[optional port number, or ipaddr:port or unix:/path/to/sockfile]'
 
    # Validation is called explicitly each time the server is reloaded.
    requires_model_validation = False
 
    def handle(self, addrport='', *args, **options):
        if args:
            raise CommandError('Usage is runserver %s' % self.args)
            
        options['bind'] = addrport or '127.0.0.1'
        
        options['default_proc_name'] =settings.SETTINGS_MODULE

        admin_media_path = options.pop('admin_media_path', '')
        quit_command = (sys.platform == 'win32') and 'CTRL-BREAK' or 'CONTROL-C'

        print "Validating models..."
        self.validate(display_num_errors=True)
        print "\nDjango version %s, using settings %r" % (django.get_version(), 
                                            settings.SETTINGS_MODULE)
        print "Development server is running at %s" % options['bind']
        print "Quit the server with %s." % quit_command
 
        # django.core.management.base forces the locale to en-us.
        translation.activate(settings.LANGUAGE_CODE)
        DjangoApplicationCommand(options, admin_media_path).run()
