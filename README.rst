Gunicorn
--------

.. image::
    https://secure.travis-ci.org/benoitc/gunicorn.png?branch=master
    :alt: Build Status
    :target: https://travis-ci.org/benoitc/gunicorn

Gunicorn 'Green Unicorn' is a Python WSGI HTTP Server for UNIX. It's a pre-fork
worker model ported from Ruby's Unicorn_ project. The Gunicorn server is broadly
compatible with various web frameworks, simply implemented, light on server
resource usage, and fairly speedy.

Feel free to join us in `#gunicorn`_ on Freenode_.

Documentation
-------------

The documentation is hosted at http://docs.gunicorn.org.

Installation
------------

Gunicorn requires **Python 2.x >= 2.6** or **Python 3.x >= 3.2**.

Install from PyPI::

    $ pip install gunicorn


Usage
-----

Basic usage::

    $ gunicorn [OPTIONS] APP_MODULE

Where ``APP_MODULE`` is of the pattern ``$(MODULE_NAME):$(VARIABLE_NAME)``. The
module name can be a full dotted path. The variable name refers to a WSGI
callable that should be found in the specified module.

Example with test app::

    $ cd examples
    $ gunicorn --workers=2 test:app


Instrumentation
---------------

Gunicorn provides an optional instrumentation of the arbiter and
workers using the statsD_ protocol over UDP. Thanks to the
`gunicorn.instrument.statsd` module, Gunicorn becomes a statsD client
The use of UDP cleanly isolates Gunicorn from the receiving end of the statsD
metrics so that instrumentation does not cause Gunicorn to be held up by a slow
statsD consumer.

To use statsD, just tell gunicorn where the statsD server is:

    $ gunicorn --statsd-host=localhost:8125 ...

The `Statsd` logger overrides `gunicorn.glogging.Logger` to track
all requests. The following metrics are generated:

  * ``gunicorn.requests``: request rate per second
  * ``gunicorn.request.duration``: histogram of request duration (in millisecond)
  * ``gunicorn.workers``: number of workers managed by the arbiter (gauge)
  * ``gunicorn.log.critical``: rate of critical log messages
  * ``gunicorn.log.error``: rate of error log messages
  * ``gunicorn.log.warning``: rate of warning log messages
  * ``gunicorn.log.exception``: rate of exceptional log messages

To generate new metrics you can `log.info` with a few additional keywords::

    log.info("...", extra={"metric": "my.metric", "value": "1.2", "mtype": "gauge"})

License
-------

Gunicorn is released under the MIT License. See the LICENSE_ file for more
details.

.. _Unicorn: http://unicorn.bogomips.org/
.. _`#gunicorn`: http://webchat.freenode.net/?channels=gunicorn
.. _Freenode: http://freenode.net
.. _LICENSE: http://github.com/benoitc/gunicorn/blob/master/LICENSE
