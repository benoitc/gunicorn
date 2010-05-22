template: doc.html
title: FAQ

.. contents:: Questions
    :backlinks: top


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

    To increase the worker count by one::

        $ kill -TTIN $masterpid
    
    To decrease the worker count by one::

        $ kill -TTOU $masterpid

.. _design: /design.html
.. _worker_class: /configure.html#worker-class
.. _`number of workers`: /design.html#how-many-workers

