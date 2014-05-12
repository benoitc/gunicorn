.. _custom:

==================
Custom Application
==================

.. versionadded:: 19.0

Sometimes, you want to integrate Gunicorn with your WSGI application. In this
case, you can inherit from :class:`gunicorn.app.base.BaseApplication`.

Here is a small example where we create a very small WSGI app and load it with a
custom Application::

    #!/usr/bin/env python
    import gunicorn.app.base

    def handler_app(environ, start_response):
        response_body = 'Works fine'
        status = '200 OK'

        response_headers = [
            ('Content-Type', 'text/plain'),
            ('Content-Length', str(len(response_body)))
        ]

        start_response(status, response_headers)

        return [response_body]

    class StandaloneApplication(gunicorn.app.base.BaseApplication):
        def __init__(self, app, options=None):
            self.options = dict(options or {})
            self.application = app
            super(StandaloneApplication, self).__init__()

        def load_config(self):
            tmp_config = map(
                lambda item: (item[0].lower(), item[1]),
                self.options.iteritems()
            )

            config = dict(
                (key, value)
                for key, value in tmp_config
                if key in self.cfg.settings and value is not None
            )

            for key, value in config.iteritems():
                self.cfg.set(key.lower(), value)

        def load(self):
            return self.application

    if __name__ == '__main__':
        options = {
            'bind': '%s:%s' % ('127.0.0.1', '8080'),
            'workers': 4,
            # 'pidfile': pidfile,
        }
        StandaloneApplication(handler_app, options).run()
