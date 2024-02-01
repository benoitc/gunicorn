#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# An example of a standalone application using the internal API of Gunicorn.
#
#   $ python standalone_app_gthread.py
#
# Stress test to ensure there are no deadlocks (using apache bench tool)
#   $ ab -n1000 -c100 http://0.0.0.0:8080/
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import gunicorn.app.base


def handler_app(environ, start_response):
    response_body = b'Works fine'
    status = '200 OK'

    response_headers = [
        ('Content-Type', 'text/plain'),
    ]

    start_response(status, response_headers)

    return [response_body]


class StandaloneApplicationGthread(gunicorn.app.base.BaseApplication):

    def __init__(self, app, options=None):
        self.options = options or {}
        self.application = app
        super().__init__()

    def load_config(self):
        config = {key: value for key, value in self.options.items()
                  if key in self.cfg.settings and value is not None}
        for key, value in config.items():
            self.cfg.set(key.lower(), value)

    def load(self):
        return self.application


if __name__ == '__main__':
    options = {
        'bind': '%s:%s' % ('127.0.0.1', '8080'),
        'workers': 1,
        'threads': 3,
        'worker_connections': 4,
    }
    StandaloneApplicationGthread(handler_app, options).run()
