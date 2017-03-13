# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# pylint: skip-file

import pkg_resources
import sys

try:
    import configparser as ConfigParser
except ImportError:
    import ConfigParser

from paste.deploy import loadapp, loadwsgi
SERVER = loadwsgi.SERVER


def _has_logging_config(paste_file):
    cfg_parser = ConfigParser.ConfigParser()
    cfg_parser.read([paste_file])
    return cfg_parser.has_section('loggers')


def paste_config(gconfig, config_url, relative_to, global_conf=None):
    # add entry to pkg_resources
    sys.path.insert(0, relative_to)
    pkg_resources.working_set.add_entry(relative_to)

    config_url = config_url.split('#')[0]
    cx = loadwsgi.loadcontext(SERVER, config_url, relative_to=relative_to,
                              global_conf=global_conf)
    gc, lc = cx.global_conf.copy(), cx.local_conf.copy()
    cfg = {}

    host, port = lc.pop('host', ''), lc.pop('port', '')
    if host and port:
        cfg['bind'] = '%s:%s' % (host, port)
    elif host:
        cfg['bind'] = host.split(',')

    cfg['default_proc_name'] = gc.get('__file__')

    # init logging configuration
    config_file = config_url.split(':')[1]
    if _has_logging_config(config_file):
        cfg.setdefault('logconfig', config_file)

    for k, v in gc.items():
        if k not in gconfig.settings:
            continue
        cfg[k] = v

    for k, v in lc.items():
        if k not in gconfig.settings:
            continue
        cfg[k] = v

    return cfg


def load_pasteapp(config_url, relative_to, global_conf=None):
    return loadapp(config_url, relative_to=relative_to,
            global_conf=global_conf)
