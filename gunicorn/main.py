# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.


import logging
import optparse as op
import os
import pkg_resources
import re
import sys

from gunicorn.arbiter import Arbiter
from gunicorn import util

__usage__ = "%prog [OPTIONS] [APP_MODULE]"

LOG_LEVELS = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG
}

UMASK = 0

def options():
    return [
        op.make_option('-b', '--bind', dest='bind',
            help='Adress to listen on. Ex. 127.0.0.1:8000 or unix:/tmp/gunicorn.sock'),
        op.make_option('--workers', dest='workers', type='int',
            help='Number of workers to spawn. [%default]'),
        op.make_option('-p','--pid', dest='pidfile',
            help='set the background PID FILE'),
        op.make_option('-D', '--daemon', dest='daemon', action="store_true",
            help='Run daemonized in the background.'),
        op.make_option('--log-level', dest='loglevel', default='info',
            help='Log level below which to silence messages. [%default]'),
        op.make_option('--log-file', dest='logfile', default='-',
            help='Log to a file. - is stdout. [%default]'),
        op.make_option('-d', '--debug', dest='debug', action="store_true",
            default=False, help='Debug mode. only 1 worker.')
    ]

def configure_logging(opts):
    handlers = []
    if opts.logfile != "-":
        handlers.append(logging.FileHandler(opts.logfile))
    else:
        handlers.append(logging.StreamHandler())

    loglevel = LOG_LEVELS.get(opts.loglevel.lower(), logging.INFO)

    logger = logging.getLogger()
    logger.setLevel(loglevel)
    for h in handlers:
        h.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s %(message)s"))
        logger.addHandler(h)
        
def daemonize():
    if not 'GUNICORN_FD' in os.environ:
        if os.fork() == 0: 
            os.setsid()
            if os.fork() == 0:
                os.umask(UMASK)
            else:
                os._exit(0)
        else:
            os._exit(0)
        
        maxfd = util.get_maxfd()
            
        # Iterate through and close all file descriptors.
        for fd in range(0, maxfd):
            try:
                os.close(fd)
            except OSError:	# ERROR, fd wasn't open to begin with (ignored)
                pass
        
        os.open(util.REDIRECT_TO, os.O_RDWR)
        os.dup2(0, 1)
        os.dup2(0, 2)
        
def main(usage, get_app):
    parser = op.OptionParser(usage=usage, option_list=options(),
                    version="%prog 0.4")
    opts, args = parser.parse_args()
    configure_logging(opts)

    app = get_app(parser, opts, args)
    workers = opts.workers or 1
    if opts.debug:
        workers = 1
        
    bind = opts.bind or '127.0.0.1'
    if bind.startswith("unix:"):
        addr = bind.split("unix:")[1]
    else:
        if ':' in bind:
            host, port = bind.split(':', 1)
            if not port.isdigit():
                raise RuntimeError("%r is not a valid port number." % port)
            port = int(port)
        else:
            host = bind
            port = 8000
        addr = (host, port)
            
    kwargs = dict(
        debug=opts.debug,
        pidfile=opts.pidfile
    )
    
    arbiter = Arbiter(addr, workers, app, **kwargs)
    if opts.daemon:
        daemonize()
    else:
        os.setpgrp()
    arbiter.run()
    
def paste_server(app, global_conf=None, host="127.0.0.1", port=None, 
            *args, **kwargs):
    if not port:
        if ':' in host:
            host, port = host.split(':', 1)
        else:
            port = 8000
    bind_addr = (host, int(port))
    
    workers = kwargs.get("workers", 1)
    if global_conf:
        workers = int(global_conf.get('workers', workers))
        
    debug = global_conf.get('debug') == "true"
    if debug:
        # we force to one worker in debug mode.
        workers = 1
        
    pid = kwargs.get("pid")
    if global_conf:
        pid = global_conf.get('pid', pid)
        
    daemon = kwargs.get("daemon")
    if global_conf:
        daemon = global_conf.get('daemon', daemonize)
   
    kwargs = dict(
        debug=debug,
        pidfile=pid
    )

    arbiter = Arbiter(bind_addr, workers, app, **kwargs)
    if daemon == "true":
        daemonize()
    else:
        os.setpgrp()
    arbiter.run()
    
def run():
    sys.path.insert(0, os.getcwd())
    
    def get_app(parser, opts, args):
        if len(args) != 1:
            parser.error("No application module specified.")

        try:
            return util.import_app(args[0])
        except:
            parser.error("Failed to import application module.")

    main(__usage__, get_app)
    
def run_django():
    import django.core.handlers.wsgi

    PROJECT_PATH = os.getcwd()
    if not os.path.isfile(os.path.join(PROJECT_PATH, "settings.py")):
        print >>sys.stderr, "settings file not found."
        sys.exit(1)

    PROJECT_NAME = os.path.split(PROJECT_PATH)[-1]

    sys.path.insert(0, PROJECT_PATH)
    sys.path.append(os.path.join(PROJECT_PATH, os.pardir))

    # set environ
    os.environ['DJANGO_SETTINGS_MODULE'] = '%s.settings' % PROJECT_NAME


    def get_app(parser, opts, args):
        # django wsgi app
        return django.core.handlers.wsgi.WSGIHandler()

    main(__usage__, get_app)
    
def run_paster():
    
    import os
    
    from paste.deploy import loadapp, loadwsgi

    __usage__ = "%prog [OPTIONS] APP_MODULE"

    _scheme_re = re.compile(r'^[a-z][a-z]+:', re.I)


    def get_app(parser, opts, args):
        if len(args) != 1:
            parser.error("No applicantion name specified.")

        config_file = os.path.abspath(os.path.normpath(
                            os.path.join(os.getcwd(), args[0])))

        if not os.path.exists(config_file):
            parser.error("Config file not found.")

        config_url = 'config:%s' % config_file
        relative_to = os.path.dirname(config_file)

        # load module in sys path
        sys.path.insert(0, relative_to)

        # add to eggs
        pkg_resources.working_set.add_entry(relative_to)
        ctx = loadwsgi.loadcontext(loadwsgi.SERVER, config_url,
                                relative_to=relative_to)

        if opts.workers:
            workers = opts.workers
        else:
            workers = int(ctx.local_conf.get('workers', 1))

        host = opts.host or ctx.local_conf.get('host', '127.0.0.1')
        port = opts.port or int(ctx.local_conf.get('port', 8000))
        bind = "%s:%s" % (host, port)

        debug = ctx.global_conf.get('debug') == "true"
        if debug:
            # we force to one worker in debug mode.
            workers = 1

        opts.workers=workers

        app = loadapp(config_url, relative_to=relative_to)
        return app

    main(__usage__, get_app)
    