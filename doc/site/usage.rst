template: doc.html
title: Command Line Usage

Usage
=====

After installing Gunicorn you will have access to three command line scripts
that can be used for serving the various supported web frameworks: ``gunicorn``,
``gunicorn_django``, and ``gunicorn_paster``.

Commonly Used Arguments
-----------------------

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

There are various other parameters that affect user privileges, logging, etc.
You can see the complete list at the bottom of this page or as expected with::

    $ gunicorn -h

gunicorn
--------

The first and most basic script is used to server 'bare' WSGI applications
that don't require a translation layer. Basic usage::

    $ gunicorn [OPTIONS] APP_MODULE

Where ``APP_MODULE`` is of the pattern ``$(MODULE_NAME):$(VARIABLE_NAME)``. The
module name can be a full dotted path. The variable name refers to a WSGI
callable that should be found in the specified module.

Example with test app::

    $ cd examples
    $ gunicorn --workers=2 test:app
    
gunicorn_django
---------------

You might not have guessed it, but this script is used to server Django
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
---------------

Yeah, for Paster-compatible frameworks (Pylons, TurboGears 2, ...). We
apologize for the lack of script name creativity. And some usage::

    $ gunicorn_paster [OPTIONS] paste_config.ini

Simple example::

    $ cd yourpasteproject
    $ gunicorn_paste --workers=2 development.ini

If you're wanting to keep on keeping on with the usual paster serve command,
you can specify the Gunicorn server settings in your configuration file::

    [server:main]
    use = egg:gunicorn#main
    host = 127.0.0.1
    port = 5000

And then as per usual::

    $ cd yourpasteproject
    $ paster serve development.ini workers=2

Full Command Line Usage
-----------------------

::

    $ gunicorn -h
    Usage: gunicorn [OPTIONS] APP_MODULE

    Options:
      -c CONFIG, --config=CONFIG
                            Config file. [none]
      -b BIND, --bind=BIND  Adress to listen on. Ex. 127.0.0.1:8000 or
                            unix:/tmp/gunicorn.sock
      -w WORKERS, --workers=WORKERS
                            Number of workers to spawn. [1]
      -k WORKER_CLASS, --worker-class=WORKER_CLASS
                            The type of request processing to use
                            [egg:gunicorn#sync]
      -p PIDFILE, --pid=PIDFILE
                            set the background PID FILE
      -D, --daemon          Run daemonized in the background.
      -m UMASK, --umask=UMASK
                            Define umask of daemon process
      -u USER, --user=USER  Change worker user
      -g GROUP, --group=GROUP
                            Change worker group
      -n PROC_NAME, --name=PROC_NAME
                            Process name
      --log-level=LOGLEVEL  Log level below which to silence messages. [info]
      --log-file=LOGFILE    Log to a file. - equals stdout. [-]
      -d, --debug           Debug mode. only 1 worker.
      --spew                Install a trace hook
      --version             show program's version number and exit
      -h, --help            show this help message and exit

Framework Examples
------------------

This is an incomplete list of examples of using Gunicorn with various
Python web frameworks. If you have an example to add you're very much
invited to submit a ticket to the `issue tracker`_ to have it included.

Itty
++++

Itty comes with builtin Gunicorn support. The Itty "Hello, world!" looks
like such::

    from itty import *

    @get('/')
    def index(request):
        return 'Hello World!'

    run_itty(server='gunicorn')

Flask
+++++

Flask applications are WSGI compatible. Given this Flask app in an importable
Python module "helloflask.py"::

    from flask import Flask
    app = Flask(__name__)

    @app.route("/")
    def hello():
        return "Hello World!"

Gunicorn can then be used to run it as such::

    $ gunicorn helloflask:app

Remember, if you're just trying to get things up and runnign that "importable"
can be as simple as "exists in the current directory".

.. _FAQ: faq.html
.. _`production page`: deployment.html
.. _`config file`: configuration.html
.. _setproctitle: http://pypi.python.org/pypi/setproctitle/
.. _`issue tracker`: http://github.com/benoitc/gunicorn/issues
