About
-----

Gunicorn 'Green Unicorn' is a Python WSGI HTTP Server for UNIX. It's a pre-fork
worker model ported from Ruby's Unicorn_ project. The Gunicorn server is broadly
compatible with various web frameworks, simply implemented, light on server
resource usage, and fairly speedy.

It submits some basic metrics via statsd (udp/8125).

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

After installing Gunicorn you will have access to the command line script
``gunicorn``.

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

Integration
-----------

We also provide integration for both Django and Paster applications.

Django
++++++

gunicorn just needs to be called with a the location of a WSGI
application object.:

    gunicorn [OPTIONS] APP_MODULE

Where APP_MODULE is of the pattern MODULE_NAME:VARIABLE_NAME. The module
name should be a full dotted path. The variable name refers to a WSGI
callable that should be found in the specified module.

So for a typical Django project, invoking gunicorn would look like:

    gunicorn myproject.wsgi:application

(This requires that your project be on the Python path; the simplest way
to ensure that is to run this command from the same directory as your
manage.py file.)

You can use the
`--env <http://docs.gunicorn.org/en/latest/settings.html#raw-env>`_ option
to set the path to load the settings. In case you need it you can also
add your application path to PYTHONPATH using the
`--pythonpath <http://docs.gunicorn.org/en/latest/settings.html#pythonpath>`_
option.

Paste
+++++

If you are a user/developer of a paste-compatible framework/app (as
Pyramid, Pylons and Turbogears) you can use the gunicorn
`--paste <http://docs.gunicorn.org/en/latest/settings.html#paste>`_ option
to run your application.

For example:

    gunicorn --paste development.ini -b :8080 --chdir /path/to/project

It is all here. No configuration files nor additional python modules to
write !!

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
