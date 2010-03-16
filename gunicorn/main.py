# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import logging
import optparse as op
import os
import pkg_resources
import sys

from gunicorn.config import Config
from gunicorn import util, __version__

LOG_LEVELS = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG
}

UMASK = "0"

def options():
    """ build command lines options passed to OptParse object """
    return [
        op.make_option('-c', '--config', dest='config', type='string',
            help='Config file. [%default]'),
        op.make_option('-b', '--bind', dest='bind',
            help='Adress to listen on. Ex. 127.0.0.1:8000 or unix:/tmp/gunicorn.sock'),
        op.make_option('-w', '--workers', dest='workers',
            help='Number of workers to spawn. [1]'),
        op.make_option('-a', '--arbiter', dest='arbiter',
            help="gunicorn arbiter entry point or module "+
            "[egg:gunicorn#main]"),
        op.make_option('-p','--pid', dest='pidfile',
            help='set the background PID FILE'),
        op.make_option('-D', '--daemon', dest='daemon', action="store_true",
            help='Run daemonized in the background.'),
        op.make_option('-m', '--umask', dest="umask", type='string', 
            help="Define umask of daemon process"),
        op.make_option('-u', '--user', dest="user", 
            help="Change worker user"),
        op.make_option('-g', '--group', dest="group", 
            help="Change worker group"),
        op.make_option('-n', '--name', dest='proc_name',
            help="Process name"),
        op.make_option('--log-level', dest='loglevel',
            help='Log level below which to silence messages. [info]'),
        op.make_option('--log-file', dest='logfile',
            help='Log to a file. - equals stdout. [-]'),
        op.make_option('-d', '--debug', dest='debug', action="store_true",
            default=False, help='Debug mode. only 1 worker.')
    ]

def configure_logging(opts):
    """
    Set level of logging, and choose where to display/save logs (file or standard output).
    """
    handlers = []
    if opts['logfile'] != "-":
        handlers.append(logging.FileHandler(opts['logfile']))
    else:
        handlers.append(logging.StreamHandler())

    loglevel = LOG_LEVELS.get(opts['loglevel'].lower(), logging.INFO)

    logger = logging.getLogger('gunicorn')
    logger.setLevel(loglevel)
    format = r"%(asctime)s [%(process)d] [%(levelname)s] %(message)s"
    datefmt = r"%Y-%m-%d %H:%M:%S"
    for h in handlers:
        h.setFormatter(logging.Formatter(format, datefmt))
        logger.addHandler(h)

def daemonize():
    """ if daemon option is set, this function will daemonize the master.
    It's based on this activestate recipe :
    http://code.activestate.com/recipes/278731/
    """
    if not 'GUNICORN_FD' in os.environ:
        if os.fork() == 0: 
            os.setsid()
            if os.fork() != 0:
                os.umask(0) 
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
    """ function used by different runners to setup options 
    ans launch the arbiter. """
    
    parser = op.OptionParser(usage=usage, option_list=options(),
                    version="%prog " + __version__)
    opts, args = parser.parse_args()
    
    app = get_app(parser, opts, args)
    conf = Config(opts.__dict__, opts.config)
    arbiter = conf.arbiter(conf.address, conf.workers, app, config=conf, 
                debug=conf['debug'], pidfile=conf['pidfile'])
    if conf['daemon']:
        daemonize()
    else:
        os.setpgrp()
    configure_logging(conf)
    arbiter.run()
    
def paste_server(app, global_conf=None, host="127.0.0.1", port=None, 
            *args, **kwargs):
    """ Paster server entrypoint to add to your paster ini file:
    
        [server:main]
        use = egg:gunicorn#main
        host = 127.0.0.1
        port = 5000
    
    """
    options = kwargs.copy()
    if port and not host.startswith("unix:"):
        bind = "%s:%s" % (host, port)
    else:
        bind = host
    options['bind'] = bind

    if global_conf:
        for key, value in list(global_conf.items()):
            if value and value is not None:
                if key == "debug":
                    value = (value == "true")
                options[key] = value
        options['default_proc_name'] = options['__file__']
           
    conf = Config(options)
    arbiter = conf.arbiter(conf.address, conf.workers, app, debug=conf["debug"], 
                    pidfile=conf["pidfile"], config=conf)
    if conf["daemon"] :
        daemonize()
    else:
        os.setpgrp()
    configure_logging(conf)
    arbiter.run()
    
def run():
    """ main runner used for gunicorn command to launch generic wsgi application """
    
    sys.path.insert(0, os.getcwd())
    
    def get_app(parser, opts, args):
        if len(args) != 1:
            parser.error("No application module specified.")


        opts.default_proc_name = args[0]
            
        try:
            return util.import_app(args[0])
        except:
            parser.error("Failed to import application module.")

    main("%prog [OPTIONS] APP_MODULE", get_app)
    
def run_django():
    """ django runner for gunicorn_django command used to launch django applications """
    
    def settings_notfound(path):
        error = "Settings file '%s' not found in current folder.\n" % path
        sys.stderr.write(error)
        sys.stderr.flush()
        sys.exit(1)

    def get_app(parser, opts, args):
        import django.core.handlers.wsgi

        project_path = os.getcwd()
        
        if args:
            settings_path = os.path.abspath(os.path.normpath(args[0]))
            if not os.path.exists(settings_path):
                settings_notfound(settings_path)
            else:
                project_path = os.path.dirname(settings_path)
        else:
             settings_path = os.path.join(project_path, "settings.py")
             if not os.path.exists(settings_path):
                 settings_notfound(settings_path)
        
        project_name = os.path.split(project_path)[-1]

        sys.path.insert(0, project_path)
        sys.path.append(os.path.join(project_path, os.pardir))

        # set environ
        settings_name, ext  = os.path.splitext(os.path.basename(settings_path))
        
        settings_modname = '%s.%s' % (project_name,  settings_name)
        os.environ['DJANGO_SETTINGS_MODULE'] = settings_modname
                                                
        opts.default_proc_name  = settings_modname
        
        # django wsgi app
        return django.core.handlers.wsgi.WSGIHandler()

    main("%prog [OPTIONS] [SETTINGS_PATH]", get_app)
    
def run_paster():
    """ runner used for gunicorn_paster command to launch paster compatible applications 
    (pylons, turbogears2, ...) """
    from paste.deploy import loadapp, loadwsgi

    def get_app(parser, opts, args):
        if len(args) != 1:
            parser.error("No application name specified.")

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

        if not opts.workers:
            opts.workers = ctx.local_conf.get('workers', 1)

        if not opts.umask:
            opts.umask = int(ctx.local_conf.get('umask', UMASK))
            
        if not opts.group:
            opts.group = ctx.local_conf.get('group')
        
        if not opts.user:
            opts.user = ctx.local_conf.get('user')
     
        if not opts.bind:
            host = ctx.local_conf.get('host')
            port = ctx.local_conf.get('port')
            if host:
                if port:
                    bind = "%s:%s" % (host, port)
                else:
                    bind = host
                opts.bind = bind

        if not opts.debug:
            opts.debug = (ctx.global_conf.get('debug') == "true")
            
        opts.default_proc_name= ctx.global_conf.get('__file__')

        app = loadapp(config_url, relative_to=relative_to)
        return app

    main("%prog [OPTIONS] pasteconfig.ini", get_app)
    
