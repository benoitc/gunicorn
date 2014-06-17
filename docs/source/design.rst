
.. _design:

======
Design
======

A brief description of an architecture of Gunicorn.

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

AsyncIO Workers
---------------

These workers are compatible with python3. You have two kind of workers.

The worker `gthread` is a threaded worker. It accepts connections in the
main loop, accepted connections are are added to the thread pool as a
connection job. On keepalive connections are put back in the loop
waiting for an event. If no event happen after the keep alive timeout,
the connection is closed.

The worker `gaiohttp` is a full asyncio worker using aiohttp_.

Choosing a Worker Type
======================

The default synchronous workers assume that your application is resource bound
in terms of CPU and network bandwidth. Generally this means that your
application shouldn't do anything that takes an undefined amount of time. For
instance, a request to the internet meets this criteria. At some point the
external network will fail in such a way that clients will pile up on your
servers.

This resource bound assumption is why we require a buffering proxy in front of a
default configuration Gunicorn. If you exposed synchronous workers to the
internet, a DOS attack would be trivial by creating a load that trickles data to
the servers. For the curious, Slowloris_ is an example of this type of load.

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
worker processes will start thrashing system resources decreasing the throughput
of the entire system.

How Many Threads?
===================

Since Gunicorn 19, a threads option can be used to process requests in multiple
threads. Using threads assumes use of the sync worker. One benefit from threads
is that requests can take longer than the worker timeout while notifying the
master process that it is not frozen and should not be killed. Depending on the
system, using multiple threads, multiple worker processes, or some mixture, may
yield the best results. For example, CPython may not perform as well as Jython
when using threads, as threading is implemented differently by each. Using
threads instead of processes is a good way to reduce the memory footprint of
Gunicorn, while still allowing for application upgrades using the reload signal,
as the application code will be shared among workers but loaded only in the
worker processes (unlike when using the preload setting, which loads the code in
the master process).

.. _Greenlets: https://github.com/python-greenlet/greenlet
.. _Eventlet: http://eventlet.net
.. _Gevent: http://gevent.org
.. _Slowloris: http://ha.ckers.org/slowloris/
.. _aiohttp: https://github.com/KeepSafe/aiohttp
