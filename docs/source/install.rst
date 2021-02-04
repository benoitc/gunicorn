============
Installation
============

.. highlight:: bash

:Requirements: **Python 3.x >= 3.5**

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

    $ pip install greenlet            # Required for both
    $ pip install eventlet            # For eventlet workers
    $ pip install gunicorn[eventlet]  # Or, using extra
    $ pip install gevent              # For gevent workers
    $ pip install gunicorn[gevent]    # Or, using extra

.. note::
    Both require ``greenlet``, which should get installed automatically.
    If its installation fails, you probably need to install
    the Python headers. These headers are available in most package
    managers. On Ubuntu the package name for ``apt-get`` is
    ``python-dev``.

    Gevent_ also requires that ``libevent`` 1.4.x or 2.0.4 is installed.
    This could be a more recent version than what is available in your
    package manager. If Gevent_ fails to build even with libevent_
    installed, this is the most likely reason.


Extra Packages
==============
Some Gunicorn options require additional packages. You can use the ``[extra]``
syntax to install these at the same time as Gunicorn.

Most extra packages are needed for alternate worker types. See the
`design docs`_ for more information on when you'll want to consider an
alternate worker type.

* ``gunicorn[eventlet]`` - Eventlet-based greenlets workers
* ``gunicorn[gevent]`` - Gevent-based greenlets workers
* ``gunicorn[gthread]`` - Threaded workers
* ``gunicorn[tornado]`` - Tornado-based workers, not recommended

If you are running more than one instance of Gunicorn, the :ref:`proc-name`
setting will help distinguish between them in tools like ``ps`` and ``top``.

* ``gunicorn[setproctitle]`` - Enables setting the process name

Multiple extras can be combined, like
``pip install gunicorn[gevent,setproctitle]``.

Debian GNU/Linux
================

If you are using Debian GNU/Linux it is recommended that you use
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

stable ("buster")
------------------

The version of Gunicorn in the Debian_ "stable" distribution is 19.9.0
(December 2020). You can install it using::

    $ sudo apt-get install gunicorn3

You can also use the most recent version 20.0.4 (December 2020) by using
`Debian Backports`_. First, copy the following line to your
``/etc/apt/sources.list``::

    deb http://ftp.debian.org/debian buster-backports main

Then, update your local package lists::

    $ sudo apt-get update

You can then install the latest version using::

    $ sudo apt-get -t buster-backports install gunicorn

oldstable ("stretch")
---------------------

While Debian releases newer than Stretch will give you gunicorn with Python 3
support no matter if you install the gunicorn or gunicorn3 package for Stretch
you specifically have to install gunicorn3 to get Python 3 support.

The version of Gunicorn in the Debian_ "oldstable" distribution is 19.6.0
(December 2020). You can install it using::

    $ sudo apt-get install gunicorn3

You can also use the most recent version 19.7.1 (December 2020) by using
`Debian Backports`_. First, copy the following line to your
``/etc/apt/sources.list``::

    deb http://ftp.debian.org/debian stretch-backports main

Then, update your local package lists::

    $ sudo apt-get update

You can then install the latest version using::

    $ sudo apt-get -t stretch-backports install gunicorn3

Testing ("bullseye") / Unstable ("sid")
---------------------------------------

"bullseye" and "sid" contain the latest released version of Gunicorn 20.0.4
(December 2020). You can install it in the usual way::

    $ sudo apt-get install gunicorn


Ubuntu
======

Ubuntu_ 20.04 LTS (Focal Fossa) or later contains the Gunicorn package by
default 20.0.4 (December 2020) so that you can install it in the usual way::

    $ sudo apt-get update
    $ sudo apt-get install gunicorn


.. _`design docs`: design.html
.. _Eventlet: http://eventlet.net
.. _Gevent: http://www.gevent.org/
.. _libevent: http://libevent.org/
.. _Debian: https://www.debian.org/
.. _`Debian Backports`: https://backports.debian.org/
.. _Ubuntu: https://www.ubuntu.com/
