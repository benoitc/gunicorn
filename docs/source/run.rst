================
Running Gunicorn
================

.. highlight:: bash

You can run Gunicorn by using commands or integrate with popular frameworks
like Django, Pyramid, or TurboGears. For deploying Gunicorn in production see
:doc:`deploy`.

Commands
========

After installing Gunicorn you will have access to the command line script
``gunicorn``.

.. _gunicorn-cmd:

gunicorn
--------

Basic usage::

    $ gunicorn [OPTIONS] [WSGI_APP]

Where ``WSGI_APP`` is of the pattern ``$(MODULE_NAME):$(VARIABLE_NAME)``. The
module name can be a full dotted path. The variable name refers to a WSGI
callable that should be found in the specified module.

.. versionchanged:: 20.1.0
    ``WSGI_APP`` is optional if it is defined in a :ref:`config` file.

Example with the test app:

.. code-block:: python

    def app(environ, start_response):
        """Simplest possible application object"""
        data = b'Hello, World!\n'
        status = '200 OK'
        response_headers = [
            ('Content-type', 'text/plain'),
            ('Content-Length', str(len(data)))
        ]
        start_response(status, response_headers)
        return iter([data])

You can now run the app with the following command:

.. code-block:: text

    $ gunicorn --workers=2 test:app

The variable name can also be a function call. In that case the name
will be imported from the module, then called to get the application
object. This is commonly referred to as the "application factory"
pattern.

.. code-block:: python

    def create_app():
        app = FrameworkApp()
        ...
        return app

.. code-block:: text

    $ gunicorn --workers=2 'test:create_app()'

Positional and keyword arguments can also be passed, but it is
recommended to load configuration from environment variables rather than
the command line.

Commonly Used Arguments
^^^^^^^^^^^^^^^^^^^^^^^

* ``-c CONFIG, --config=CONFIG`` - Specify a config file in the form
  ``$(PATH)``, ``file:$(PATH)``, or ``python:$(MODULE_NAME)``.
* ``-b BIND, --bind=BIND`` - Specify a server socket to bind. Server sockets
  can be any of ``$(HOST)``, ``$(HOST):$(PORT)``, ``fd://$(FD)``, or
  ``unix:$(PATH)``. An IP is a valid ``$(HOST)``.
* ``-w WORKERS, --workers=WORKERS`` - The number of worker processes. This
  number should generally be between 2-4 workers per core in the server.
  Check the :ref:`faq` for ideas on tuning this parameter.
* ``-k WORKERCLASS, --worker-class=WORKERCLASS`` - The type of worker process
  to run. You'll definitely want to read the production page for the
  implications of this parameter. You can set this to ``$(NAME)``
  where ``$(NAME)`` is one of ``sync``, ``eventlet``, ``gevent``,
  ``tornado``, ``gthread``.
  ``sync`` is the default. See the :ref:`worker-class` documentation for more
  information.
* ``-n APP_NAME, --name=APP_NAME`` - If setproctitle_ is installed you can
  adjust the name of Gunicorn process as they appear in the process system
  table (which affects tools like ``ps`` and ``top``).

Settings can be specified by using environment variable
:ref:`GUNICORN_CMD_ARGS <settings>`.

See :ref:`configuration` and :ref:`settings` for detailed usage.

.. _setproctitle: https://pypi.python.org/pypi/setproctitle

Integration
===========

Gunicorn also provides integration for Django and Paste Deploy applications.

Django
------

Gunicorn will look for a WSGI callable named ``application`` if not specified.
So for a typical Django project, invoking Gunicorn would look like::

    $ gunicorn myproject.wsgi


.. note::

   This requires that your project be on the Python path; the simplest way to
   ensure that is to run this command from the same directory as your
   ``manage.py`` file.

You can use the
:ref:`raw-env` option
to set the path to load the settings. In case you need it you can also
add your application path to ``PYTHONPATH`` using the
:ref:`pythonpath` option::

    $ gunicorn --env DJANGO_SETTINGS_MODULE=myproject.settings myproject.wsgi

Paste Deployment
----------------

Frameworks such as Pyramid and Turbogears are typically configured using Paste
Deployment configuration files. If you would like to use these files with
Gunicorn, there are two approaches.

As a server runner, Gunicorn can serve your application using the commands from
your framework, such as ``pserve`` or ``gearbox``. To use Gunicorn with these
commands, specify it as a server in your configuration file:

.. code-block:: ini

    [server:main]
    use = egg:gunicorn#main
    host = 127.0.0.1
    port = 8080
    workers = 3

This approach is the quickest way to get started with Gunicorn, but there are
some limitations. Gunicorn will have no control over how the application is
loaded, so settings such as :ref:`reload` will have no effect and Gunicorn will be
unable to hot upgrade a running application. Using the :ref:`daemon` option may
confuse your command line tool. Instead, use the built-in support for these
features provided by that tool. For example, run ``pserve --reload`` instead of
specifying ``reload = True`` in the server configuration block. For advanced
configuration of Gunicorn, such as :ref:`server-hooks` specifying a Gunicorn
configuration file using the ``config`` key is supported.

To use the full power of Gunicorn's reloading and hot code upgrades, use the
:ref:`paste` to run your application instead. When used this way, Gunicorn
will use the application defined by the PasteDeploy configuration file, but
Gunicorn will not use any server configuration defined in the file. Instead,
:ref:`configure gunicorn<settings>`.

For example::

    $ gunicorn --paste development.ini -b :8080 --chdir /path/to/project

Or use a different application::

    $ gunicorn --paste development.ini#admin -b :8080 --chdir /path/to/project

With both approaches, Gunicorn will use any loggers section found in Paste
Deployment configuration file, unless instructed otherwise by specifying
additional :ref:`logging settings<logging>`.
