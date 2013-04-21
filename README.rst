About
-----

Gunicorn 'Green Unicorn' is a Python WSGI HTTP Server for UNIX. It's a pre-fork
worker model ported from Ruby's Unicorn_ project. The Gunicorn server is broadly
compatible with various web frameworks, simply implemented, light on server
resource usage, and fairly speedy.

Feel free to join us in `#gunicorn`_ on freenode_.

.. image::
    https://secure.travis-ci.org/benoitc/gunicorn.png?branch=master
    :alt: Build Status
    :target: https://travis-ci.org/benoitc/gunicorn

Documentation
-------------

http://docs.gunicorn.org

Installation
------------

Gunicorn requires **Python 2.x >= 2.6** or **Python 3.x >= 3.1**.

Install from sources::

  $ python setup.py install

Or from Pypi::

  $ easy_install -U gunicorn

You may also want to install Eventlet_ or Gevent_ if you expect that your
application code may need to pause for extended periods of time during
request processing. Check out the FAQ_ for more information on when you'll
want to consider one of the alternate worker types.

To install eventlet::

    $ easy_install -U eventlet

If you encounter errors when compiling the extensions for Eventlet_ or
Gevent_ you most likely need to install a newer version of libev_ or libevent_.

Basic Usage
-----------

After installing Gunicorn you will have access to three command line scripts
that can be used for serving the various supported web frameworks: ``gunicorn``,
``gunicorn_django``, and ``gunicorn_paster``.

Commonly Used Arguments
+++++++++++++++++++++++

  * ``-c CONFIG, --config=CONFIG`` - Specify the path to a `config file`_
  * ``-b BIND, --bind=BIND`` - Specify a server socket to bind. Server sockets
    can be any of ``$(HOST)``, ``$(HOST):$(PORT)``, or ``unix:$(PATH)``.
    An IP is a valid ``$(HOST)``.
  * ``-w WORKERS, --workers=WORKERS`` - The number of worker processes. This
    number should generally be between 2-4 workers per core in the server.
    Check the FAQ_ for ideas on tuning this parameter.
  * ``-k WORKERCLASS, --worker-class=WORKERCLASS`` - The type of worker process
    to run. You'll definitely want to read the `production page`_ for the
    implications of this parameter. You can set this to ``egg:gunicorn#$(NAME)``
    where ``$(NAME)`` is one of ``sync``, ``eventlet``, ``gevent``, or
    ``tornado``. ``sync`` is the default.
  * ``-n APP_NAME, --name=APP_NAME`` - If setproctitle_ is installed you can
    adjust the name of Gunicorn process as they appear in the process system
    table (which affects tools like ``ps`` and ``top``).

    sync=gunicorn.workers.sync:SyncWorker
    eventlet=gunicorn.workers.geventlet:EventletWorker
    gevent=gunicorn.workers.ggevent:GeventWorker
    tornado

There are various other parameters that affect user privileges, logging, etc.
You can see the complete list with the expected::

    $ gunicorn -h

gunicorn
++++++++

The first and most basic script is used to serve 'bare' WSGI applications
that don't require a translation layer. Basic usage::

    $ gunicorn [OPTIONS] APP_MODULE

Where ``APP_MODULE`` is of the pattern ``$(MODULE_NAME):$(VARIABLE_NAME)``. The
module name can be a full dotted path. The variable name refers to a WSGI
callable that should be found in the specified module.

Example with test app::

    $ cd examples
    $ gunicorn --workers=2 test:app

gunicorn_django
+++++++++++++++

You might not have guessed it, but this script is used to serve Django
applications. Basic usage::

    $ gunicorn_django [OPTIONS] [SETTINGS_PATH]

By default ``SETTINGS_PATH`` will look for ``settings.py`` in the current
directory.

Example with your Django project::

    $ cd path/to/yourdjangoproject
    $ gunicorn_django --workers=2

Alternatively, you can install some Gunicorn magic directly into your Django
project and use the provided command for running the server.

First you'll need to add ``gunicorn`` to your ``INSTALLED_APPS`` in the settings
file::

    INSTALLED_APPS = (
        ...
        "gunicorn",
    )

Then you can run::

    python manage.py run_gunicorn

gunicorn_paster
+++++++++++++++

Yeah, for Paster-compatible frameworks (Pylons, TurboGears 2, ...). We
apologize for the lack of script name creativity. And some usage::

    $ gunicorn_paster [OPTIONS] paste_config.ini

Simple example::

    $ cd yourpasteproject
    $ gunicorn_paster --workers=2 development.ini

If you're wanting to keep on keeping on with the usual paster serve command,
you can specify the Gunicorn server settings in your configuration file::

    [server:main]
    use = egg:gunicorn#main
    host = 127.0.0.1
    port = 5000

And then as per usual::

    $ cd yourpasteproject
    $ paster serve development.ini workers=2

**Gunicorn paster from script**

If you'd like to run Gunicorn paster from a script instead of the command line (for example: a runapp.py to start a Pyramid app),
you can use this example to help get you started::

    import os
    import multiprocessing

    from paste.deploy import appconfig, loadapp
    from gunicorn.app.pasterapp import paste_server

    if __name__ == "__main__":

        iniFile = 'config:development.ini'
        port = int(os.environ.get("PORT", 5000))
        workers = multiprocessing.cpu_count() * 2 + 1
        worker_class = 'gevent'

        app = loadapp(iniFile, relative_to='.')
        paste_server(app, host='0.0.0.0', port=port, workers=workers, worker_class=worker_class)


LICENSE
-------

Gunicorn is released under the MIT License. See the LICENSE_ file for more
details.

.. _Unicorn: http://unicorn.bogomips.org/
.. _`#gunicorn`: http://webchat.freenode.net/?channels=gunicorn
.. _freenode: http://freenode.net
.. _Eventlet: http://eventlet.net
.. _Gevent: http://gevent.org
.. _FAQ: http://docs.gunicorn.org/en/latest/faq.html
.. _libev: http://software.schmorp.de/pkg/libev.html
.. _libevent: http://monkey.org/~provos/libevent
.. _`production page`: http://docs.gunicorn.org/en/latest/deploy.html
.. _`config file`: http://docs.gunicorn.org/en/latest/configure.html
.. _setproctitle: http://pypi.python.org/pypi/setproctitle/
.. _LICENSE: http://github.com/benoitc/gunicorn/blob/master/LICENSE
