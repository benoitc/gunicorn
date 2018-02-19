.. _instrumentation:

===============
Instrumentation
===============

.. versionadded:: 19.1

Gunicorn provides an optional instrumentation of the arbiter and
workers using the statsD_ protocol over UDP. Thanks to the
``gunicorn.instrument.statsd`` module, Gunicorn becomes a statsD client.
The use of UDP cleanly isolates Gunicorn from the receiving end of the statsD
metrics so that instrumentation does not cause Gunicorn to be held up by a slow
statsD consumer.

To use statsD, just tell Gunicorn where the statsD server is:

.. code-block:: bash

    $ gunicorn --statsd-host=localhost:8125 --statsd-prefix=service.app ...

The ``Statsd`` logger overrides ``gunicorn.glogging.Logger`` to track
all requests. The following metrics are generated:

* ``gunicorn.requests``: request rate per second
* ``gunicorn.request.duration``: histogram of request duration (in millisecond)
* ``gunicorn.workers``: number of workers managed by the arbiter (gauge)
* ``gunicorn.log.critical``: rate of critical log messages
* ``gunicorn.log.error``: rate of error log messages
* ``gunicorn.log.warning``: rate of warning log messages
* ``gunicorn.log.exception``: rate of exceptional log messages

See the statsd-host_ setting for more information.

.. _statsd-host: settings.html#statsd-host
.. _statsD: https://github.com/etsy/statsd
