
.. _design:

======
Design
======

A brief description of the architecture of Gunicorn.

Server Model
============

Gunicorn is based on the pre-fork worker model. This means that there is a
central master process that manages a set of worker processes. The master
never knows anything about individual clients. All requests and responses are
handled completely by worker processes.

Master
------

The master process is a simple loop that listens for various process signals
and reacts accordingly. It manages the list of running workers by listening
for signals like TTIN, TTOU, and CHLD. TTIN and TTOU tell the master to
increase or decrease the number of running workers. CHLD indicates that a child
process has terminated, in this case the master process automatically restarts
the failed worker.

Sync Workers
------------

The most basic and the default worker type is a synchronous worker class that
handles a single request at a time. This model is the simplest to reason about
as any errors will affect at most a single request. Though as we describe below
only processing a single request at a time requires some assumptions about how
applications are programmed.

``sync`` worker does not support persistent connections - each connection is
closed after response has been sent (even if you manually add ``Keep-Alive``
or ``Connection: keep-alive`` header in your application).

Async Workers
-------------

The asynchronous workers available are based on Greenlets_ (via Eventlet_ and
Gevent_). Greenlets are an implementation of cooperative multi-threading for
Python. In general, an application should be able to make use of these worker
classes with no changes.

Tornado Workers
---------------

There's also a Tornado worker class. It can be used to write applications using
the Tornado framework. Although the Tornado workers are capable of serving a
WSGI application, this is not a recommended configuration.


.. _asyncio-workers:

AsyncIO Workers
---------------

These workers are compatible with python3. You have two kind of workers.

The worker `gthread` is a threaded worker. It accepts connections in the
main loop, accepted connections are added to the thread pool as a
connection job. On keepalive connections are put back in the loop
waiting for an event. If no event happen after the keep alive timeout,
the connection is closed.

The worker `gaiohttp` is a full asyncio worker using aiohttp_.

.. note::
   The ``gaiohttp`` worker requires the aiohttp_ module to be installed.
   aiohttp_ has removed its native WSGI application support in version 2.
   If you want to continue to use the ``gaiohttp`` worker with your WSGI
   application (e.g. an application that uses Flask or Django), there are
   three options available:

   #. Install aiohttp_ version 1.3.5 instead of version 2::

        $ pip install aiohttp==1.3.5

   #. Use aiohttp_wsgi_ to wrap your WSGI application. You can take a look
      at the `example`_ in the Gunicorn repository.
   #. Port your application to use aiohttp_'s ``web.Application`` API.
   #. Use the ``aiohttp.worker.GunicornWebWorker`` worker instead of the
      deprecated ``gaiohttp`` worker.

Choosing a Worker Type
======================

The default synchronous workers assume that your application is resource-bound
in terms of CPU and network bandwidth. Generally this means that your
application shouldn't do anything that takes an undefined amount of time. An
example of something that takes an undefined amount of time is a request to the
internet. At some point the external network will fail in such a way that
clients will pile up on your servers. So, in this sense, any web application
which makes outgoing requests to APIs will benefit from an asynchronous worker.

This resource bound assumption is why we require a buffering proxy in front of
a default configuration Gunicorn. If you exposed synchronous workers to the
internet, a DOS attack would be trivial by creating a load that trickles data to
the servers. For the curious, Hey_ is an example of this type of load.


Some examples of behavior requiring asynchronous workers:

  * Applications making long blocking calls (Ie, external web services)
  * Serving requests directly to the internet
  * Streaming requests and responses
  * Long polling
  * Web sockets
  * Comet

How Many Workers?
=================

DO NOT scale the number of workers to the number of clients you expect to have.
Gunicorn should only need 4-12 worker processes to handle hundreds or thousands
of requests per second.

Gunicorn relies on the operating system to provide all of the load balancing
when handling requests. Generally we recommend ``(2 x $num_cores) + 1`` as the
number of workers to start off with. While not overly scientific, the formula
is based on the assumption that for a given core, one worker will be reading
or writing from the socket while the other worker is processing a request.

Obviously, your particular hardware and application are going to affect the
optimal number of workers. Our recommendation is to start with the above guess
and tune using TTIN and TTOU signals while the application is under load.

Always remember, there is such a thing as too many workers. After a point your
worker processes will start thrashing system resources decreasing the
throughput of the entire system.

How Many Threads?
===================

Since Gunicorn 19, a threads option can be used to process requests in multiple
threads. Using threads assumes use of the gthread worker. One benefit from threads
is that requests can take longer than the worker timeout while notifying the
master process that it is not frozen and should not be killed. Depending on the
system, using multiple threads, multiple worker processes, or some mixture, may
yield the best results. For example, CPython may not perform as well as Jython
when using threads, as threading is implemented differently by each. Using
threads instead of processes is a good way to reduce the memory footprint of
Gunicorn, while still allowing for application upgrades using the reload
signal, as the application code will be shared among workers but loaded only in
the worker processes (unlike when using the preload setting, which loads the
code in the master process).

.. note::
   Under Python 2.x, you need to install the 'futures' package to use this 
   feature.

.. _Greenlets: https://github.com/python-greenlet/greenlet
.. _Eventlet: http://eventlet.net/
.. _Gevent: http://www.gevent.org/
.. _Hey: https://github.com/rakyll/hey
.. _aiohttp: https://aiohttp.readthedocs.io/en/stable/
.. _aiohttp_wsgi: https://aiohttp-wsgi.readthedocs.io/en/stable/index.html
.. _`example`: https://github.com/benoitc/gunicorn/blob/master/examples/frameworks/flaskapp_aiohttp_wsgi.py
