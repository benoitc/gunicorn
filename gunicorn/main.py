# -*- coding: utf-8 -
#
# 2009 (c) Benoit Chesneau <benoitc@e-engura.com> 
# 2009 (c) Paul J. Davis <paul.joseph.davis@gmail.com>
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following
# conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.

import logging
import optparse as op
import os
import sys

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

