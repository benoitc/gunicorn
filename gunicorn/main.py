# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.


import logging
import optparse as op

from gunicorn.arbiter import Arbiter

LOG_LEVELS = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG
}

def options():
    return [
        op.make_option('--host', dest='host', default='127.0.0.1',
            help='Host to listen on. [%default]'),
        op.make_option('--port', dest='port', default=8000, type='int',
            help='Port to listen on. [%default]'),
        op.make_option('--workers', dest='workers', default=1, type='int',
            help='Number of workers to spawn. [%default]'),
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
        h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(h)

def main(usage, get_app):
    parser = op.OptionParser(usage=usage, option_list=options())
    opts, args = parser.parse_args()
    configure_logging(opts)

    app = get_app(parser, opts, args)
    workers = opts.workers
    if opts.debug:
        workers = 1
    
    arbiter = Arbiter((opts.host, opts.port), workers, app, 
                    opts.debug)
    arbiter.run()
    
def paste_server(app, global_conf=None, host="127.0.0.1", port=None, 
            *args, **kwargs):
    if not port:
        if ':' in host:
            host, port = host.split(':', 1)
        else:
            port = 8000
    bind_addr = (host, int(port))
    
    if not global_conf:
        workers=1
    else:
        workers = int(global_conf.get('workers', 1))
    
    debug = global_conf.get('debug') == "true"
    if debug:
        # we force to one worker in debug mode.
        workers = 1
    
    arbiter = Arbiter(bind_addr, workers, app, 
                    debug)
    arbiter.run()