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
            help='Log to a file. - is stdout. [%default]')
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
    arbiter = Arbiter((opts.host, opts.port), opts.workers, app)
    arbiter.run()

