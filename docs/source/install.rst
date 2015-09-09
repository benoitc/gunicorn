============
Installation
============

.. highlight:: bash

:Requirements: **Python 2.x >= 2.6** or **Python 3.x >= 3.2**

To install the latest released version of Gunicorn::

  $ pip install gunicorn

From Source
===========

You can install Gunicorn from source just as you would install any other
Python package::

    $ pip install git+https://github.com/benoitc/gunicorn.git

This will allow you to keep up to date with development on GitHub::

    $ pip install -U git+https://github.com/benoitc/gunicorn.git


Async Workers
=============

You may also want to install Eventlet_ or Gevent_ if you expect that your
application code may need to pause for extended periods of time during request
processing. Check out the `design docs`_ for more information on when you'll
want to consider one of the alternate worker types.

::

    $ pip install greenlet  # Required for both
    $ pip install eventlet  # For eventlet workers
    $ pip install gevent    # For gevent workers

.. note::
    If installing ``greenlet`` fails you probably need to install
    the Python headers. These headers are available in most package
    managers. On Ubuntu the package name for ``apt-get`` is
    ``python-dev``.

    Gevent_ also requires that ``libevent`` 1.4.x or 2.0.4 is installed.
    This could be a more recent version than what is available in your
    package manager. If Gevent_ fails to build even with libevent_
    installed, this is the most likely reason.


Debian GNU/Linux
================

If you are using Debian GNU/Linux and it is recommended that you use
system packages to install Gunicorn except maybe when you want to use
different versions of Gunicorn with virtualenv. This has a number of
advantages:

* Zero-effort installation: Automatically starts multiple Gunicorn instances
  based on configurations defined in ``/etc/gunicorn.d``.

* Sensible default locations for logs (``/var/log/gunicorn``). Logs
  can be automatically rotated and compressed using ``logrotate``.

* Improved security: Can easily run each Gunicorn instance with a dedicated
  UNIX user/group.

* Sensible upgrade path: Upgrades to newer versions result in less downtime,
  handle conflicting changes in configuration options, and can be quickly
  rolled back in case of incompatibility. The package can also be purged
  entirely from the system in seconds.

stable ("jessie")
-----------------

The version of Gunicorn in the Debian_ "stable" distribution is 19.0 (June
2014). You can install it using::

    $ sudo apt-get install gunicorn

You can also use the most recent version by using `Debian Backports`_.
First, copy the following line to your ``/etc/apt/sources.list``::

    deb http://backports.debian.org/debian-backports jessie-backports main

Then, update your local package lists::

    $ sudo apt-get update

You can then install the latest version using::

    $ sudo apt-get -t jessie-backports install gunicorn

oldstable ("wheezy")
--------------------

The version of Gunicorn in the Debian_ "oldstable" distribution is 0.14.5 (June
2012). you can install it using::

    $ sudo apt-get install gunicorn

You can also use the most recent version by using `Debian Backports`_.
First, copy the following line to your ``/etc/apt/sources.list``::

    deb http://backports.debian.org/debian-backports wheezy-backports main

Then, update your local package lists::

    $ sudo apt-get update

You can then install the latest version using::

    $ sudo apt-get -t wheezy-backports install gunicorn

Testing ("stretch") / Unstable ("sid")
--------------------------------------

"stretch" and "sid" contain the latest released version of Gunicorn. You can
install it in the usual way::

    $ sudo apt-get install gunicorn


Ubuntu
======

Ubuntu_ 12.04 (trusty) or later contains Gunicorn package by default so that
you can install it in the usual way::

    $ sudo apt-get update
    $ sudo apt-get install gunicorn


.. _`design docs`: design.html
.. _Eventlet: http://eventlet.net
.. _Gevent: http://gevent.org
.. _libevent: http://monkey.org/~provos/libevent
.. _Debian: http://www.debian.org/
.. _`Debian Backports`: http://backports.debian.org/
.. _Ubuntu: http://www.ubuntu.com/
