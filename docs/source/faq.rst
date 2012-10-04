===
FAQ
===

WSGI Bits
=========

How do I set SCRIPT_NAME?
-------------------------

By default ``SCRIPT_NAME`` is an empy string. The value could be set by
setting ``SCRIPT_NAME`` in the environment or as an HTTP header.


Server Stuff
============

How do I reload my application in Gunicorn?
-------------------------------------------

You can gracefully reload by sending HUP signal to gunicorn::

    $ kill -HUP masterpid

How might I test a proxy configuration?
---------------------------------------

The Slowloris_ script is a great way to test that your proxy is correctly
buffering responses for the synchronous workers.

How can I name processes?
-------------------------

If you install the Python package setproctitle_ Gunicorn will set the process
names to something a bit more meaningful. This will affect the output you see
in tools like ``ps`` and ``top``. This helps for distinguishing the master
process as well as between masters when running more than one app on a single
machine. See the proc_name_ setting for more information.

Gunicorn fails to start with upstart
------------------------------------

Make sure you run gunicorn with ``--daemon`` option.

Why is there no HTTP Keep-Alive?
--------------------------------

The default Sync workers are designed to run behind Nginx which only uses
HTTP/1.0 with its upstream servers. If you want to deploy Gunicorn to
handle unbuffered requests (ie, serving requests directly from the internet)
you should use one of the async workers.

.. _slowloris: http://ha.ckers.org/slowloris/
.. _setproctitle: http://pypi.python.org/pypi/setproctitle
.. _proc_name: /configure.html#proc-name


Worker Processes
================

How do I know which type of worker to use?
------------------------------------------

Read the design_ page for help on the various worker types.

What types of workers are there?
--------------------------------

Check out the configuration docs for worker_class_

How can I figure out the best number of worker processes?
---------------------------------------------------------

Here is our recommendation for tuning the `number of workers`_.

How can I change the number of workers dynamically?
---------------------------------------------------

TTIN and TTOU signals can be sent to the master to increase or decrease
the number of workers.

To increase the worker count by one::

    $ kill -TTIN $masterpid

To decrease the worker count by one::

    $ kill -TTOU $masterpid

.. _design: /design.html
.. _worker_class: /configure.html#worker-class
.. _`number of workers`: /design.html#how-many-workers

Kernel Parameters
=================

When dealing with large numbers of concurrent connections there are a handful of
kernel parameters that you might need to adjust. Generally these should only
affect sites with a very large concurrent load. These parameters are not
specific to Gunicorn, they would apply to any sort of network server you may be
running.

These commands are for Linux. Your particular OS may have slightly different
parameters.

How can I increase the maximum number of file descriptors?
----------------------------------------------------------

One of the first settings that usually needs to be bumped is the maximum number
of open file descriptors for a given process. For the confused out there,
remember that Unices treat sockets as files.

::

    $ sudo ulimit -n 2048

How can I increase the maximum socket backlog?
----------------------------------------------

Listening sockets have an associated queue of incoming connections that are
waiting to be accepted. If you happen to have a stampede of clients that fill up
this queue new connections will eventually start getting dropped.

::

    $ sudo sysctl -w net.core.somaxconn="2048"
