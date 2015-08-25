================
Running Gunicorn
================

.. highlight:: bash

You can run Gunicorn by using commands or integrate with Django or Paster. For
deploying Gunicorn in production see :doc:`deploy`.

Commands
========

After installing Gunicorn you will have access to the command line script
``gunicorn``.

gunicorn
--------

Basic usage::

    $ gunicorn [OPTIONS] APP_MODULE

Where ``APP_MODULE`` is of the pattern ``$(MODULE_NAME):$(VARIABLE_NAME)``. The
module name can be a full dotted path. The variable name refers to a WSGI
callable that should be found in the specified module.

Example with the test app:

.. code-block:: python

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

You can now run the app with the following command::

    $ gunicorn --workers=2 test:app


Commonly Used Arguments
^^^^^^^^^^^^^^^^^^^^^^^

* ``-c CONFIG, --config=CONFIG`` - Specify a config file in the form
  ``$(PATH)``, ``file:$(PATH)``, or ``python:$(MODULE_NAME)``.
* ``-b BIND, --bind=BIND`` - Specify a server socket to bind. Server sockets
  can be any of ``$(HOST)``, ``$(HOST):$(PORT)``, or ``unix:$(PATH)``.
  An IP is a valid ``$(HOST)``.
* ``-w WORKERS, --workers=WORKERS`` - The number of worker processes. This
  number should generally be between 2-4 workers per core in the server.
  Check the :ref:`faq` for ideas on tuning this parameter.
* ``-k WORKERCLASS, --worker-class=WORKERCLASS`` - The type of worker process
  to run. You'll definitely want to read the production page for the
  implications of this parameter. You can set this to ``$(NAME)``
  where ``$(NAME)`` is one of ``sync``, ``eventlet``, ``gevent``, or
  ``tornado``, ``gthread``, ``gaiohttp``. ``sync`` is the default.
* ``-n APP_NAME, --name=APP_NAME`` - If setproctitle_ is installed you can
  adjust the name of Gunicorn process as they appear in the process system
  table (which affects tools like ``ps`` and ``top``).

See :ref:`configuration` and :ref:`settings` for detailed usage.

.. _setproctitle: http://pypi.python.org/pypi/setproctitle/

Integration
===========

We also provide integration for both Django and Paster applications.

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
`--env <http://docs.gunicorn.org/en/latest/settings.html#raw-env>`_ option
to set the path to load the settings. In case you need it you can also
add your application path to ``PYTHONPATH`` using the
`--pythonpath <http://docs.gunicorn.org/en/latest/settings.html#pythonpath>`_
option::

    $ gunicorn --env DJANGO_SETTINGS_MODULE=myproject.settings myproject.wsgi

Paste
-----

If you are a user/developer of a paste-compatible framework/app (as
Pyramid, Pylons and Turbogears) you can use the
`--paste <http://docs.gunicorn.org/en/latest/settings.html#paste>`_ option
to run your application.

For example::

    $ gunicorn --paste development.ini -b :8080 --chdir /path/to/project

Or use a different application::

    $ gunicorn --paste development.ini#admin -b :8080 --chdir /path/to/project

It is all here. No configuration files nor additional Python modules to write!
