================
Running Gunicorn
================

You can run Gunicorn by using commands or integrate with Django or Paster. For
deploying Gunicorn in production see :doc:`deploy`.

Commands
========

After installing Gunicorn you will have access to three command line scripts
that can be used for serving the various supported web frameworks:

  * ``gunicorn``
  * ``gunicorn_django``
  * ``gunicorn_paster``

gunicorn
--------

The first and most basic script is used to serve 'bare' WSGI applications
that don't require a translation layer. Basic usage::

    $ gunicorn [OPTIONS] APP_MODULE

Where ``APP_MODULE`` is of the pattern ``$(MODULE_NAME):$(VARIABLE_NAME)``. The
module name can be a full dotted path. The variable name refers to a WSGI
callable that should be found in the specified module.

Example with test app::

    $ cd examples
    $ cat test.py
    # -*- coding: utf-8 -
    #
    # This file is part of gunicorn released under the MIT license.
    # See the NOTICE for more information.

    def app(environ, start_response):
        """Simplest possible application object"""
        data = 'Hello, World!\n'
        status = '200 OK'
        response_headers = [
            ('Content-type','text/plain'),
            ('Content-Length', str(len(data)))
        ]
        start_response(status, response_headers)
        return iter([data])

    $ gunicorn --workers=2 test:app

gunicorn_django
---------------

You might not have guessed it, but this script is used to serve Django
applications. Basic usage::

    $ gunicorn_django [OPTIONS] [SETTINGS_PATH]

By default ``SETTINGS_PATH`` will look for ``settings.py`` in the current
directory.

Example with your Django project::

    $ cd path/to/yourdjangoproject
    $ gunicorn_django --workers=2

.. note:: If you run Django 1.4 or newer, it's highly recommended to
    simply run your application with the `WSGI interface
    <https://docs.djangoproject.com/en/1.4/howto/deployment/wsgi/>`_ using
    the `gunicorn`_ command.

gunicorn_paster
---------------

Yeah, for Paster-compatible frameworks (Pylons, TurboGears 2, ...). We
apologize for the lack of script name creativity. And some usage::

    $ gunicorn_paster [OPTIONS] paste_config.ini

Simple example::

    $ cd yourpasteproject
    $ gunicorn_paster --workers=2 development.ini

Integration
===========

Alternatively, we also provide integration for both Django and Paster
applications in case your deployment strategy would be better served by such
invocation styles.

Django ./manage.py
------------------

You can add a ``run_gunicorn`` command to your ``./manage.py`` simply by adding
gunicorn to your ``INSTALLED_APPS``::

    INSTALLED_APPS = (
        ...
        "gunicorn",
    )

Then you can run::

    python manage.py run_gunicorn

paster serve
------------

If you're wanting to keep on keeping on with the usual paster serve command,
you can specify the Gunicorn server settings in your configuration file::

    [server:main]
    use = egg:gunicorn#main
    host = 127.0.0.1
    port = 5000
    # Uncomment the line below to use other advanced gunicorn settings
    #config = %(here)/gunicorn.conf.py

And then as per usual::

    $ cd yourpasteproject
    $ paster serve development.ini workers=2

However, in this configuration, Gunicorn does not reload the application when
new workers are started. See the note about preloading_.

.. _preloading: configure.html#preload-app


custom application
------------------

Sometimes, you want to integrate Gunicorn with your WSGI application. In this
case, you can inherit from gunicorn.app.base.BaseApplication.

Example::

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
