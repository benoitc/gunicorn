template: doc.html
title: Install

_TOC_TOP_

.. contents::
    :backlinks: top

_TOC_BOT_

Requirements
------------

- **Python 2.x >= 2.5** (Python 3.x will be supported soon)
- setuptools >= 0.6c6
- nosetests (for the test suite only)

With easy_install
-----------------

If you don't already have ``easy_install`` available you'll want to download
and run the ``ez_setup.py`` script::

  $ curl -O http://peak.telecommunity.com/dist/ez_setup.py
  $ sudo python ez_setup.py -U setuptools

To install or upgrade to the latest released version of Gunicorn::

  $ sudo easy_install -U gunicorn

.. note::
    There is a limited support version of Gunicorn that is compatible
    with Python 2.4. This fork is managed by Randall Leeds and can be
    found `here on github`_. To install this version you must specify
    the full url to something like ``pip``. This hasn't been tested
    wtih ``easy_install`` just yet::

        $ pip install -f http://github.com/tilgovi/gunicorn/tarball/py24 gunicorn

From Source
-----------

You can install Gunicorn from source just as you would install any other
Python package. Gunicorn uses setuptools which will automatically fetch all
dependencies (including setuptools itself).

You can download a tarball of the latest sources from `GitHub Downloads`_ or
fetch them with git_::

    # Using git:
    $ git clone git://github.com/benoitc/gunicorn.git
    $ cd gunicorn

    # Or using a tarball:
    $ wget http://github.com/benoitc/gunicorn/tarball/master -o gunicorn.tar.gz
    $ tar -xvzf gunicorn.tar.gz
    $ cd gunicorn-$HASH/

    # Install
    $ sudo python setup.py install

If you've cloned the git repository, its highly recommended that you use the
``develop`` command which will allow you to use Gunicorn from the source
directory. This will allow you to keep up to date with development on GitHub as
well as make changes to the source::

    $ python setup.py develop

Async Workers
-------------

You may also want to install Eventlet_ or Gevent_ if you expect that your
application code may need to pause for extended periods of time during request
processing. Check out the `design docs`_ for more information on when you'll
want to consider one of the alternate worker types.

::

    $ easy_install -U greenlet  # Required for both
    $ easy_install -U eventlet  # For eventlet workers
    $ easy_install -U gevent    # For gevent workers

.. note::
    If installing ``greenlet`` fails you probably need to install
    the Python headers. These headers are available in most package
    managers. On Ubuntu the package name for ``apt-get`` is
    ``python-dev``.

    Gevent_ also requires that ``libevent`` 1.4.x or 2.0.4 is installed.
    This could be a more recent version than what is available in your
    package manager. If Gevent_ fails to build even with libevent_
    installed, this is the most likely reason.

Ubuntu/Debian
-------------

If you use Ubuntu_ karmic, you can update your system with packages from
our PPA_ by adding ``ppa:bchesneau/gunicorn`` to your system's Software
Sources.

Or this PPA can be added to your system manually by copying the lines below
and adding them to your system's software sources::

  deb http://ppa.launchpad.net/bchesneau/gunicorn/ubuntu karmic main 
  deb-src http://ppa.launchpad.net/bchesneau/gunicorn/ubuntu karmic main
  
Signing key
+++++++++++

::

  1024R/15E5EB06
  
Fingerprint
+++++++++++

::

  49AEEDFF5CDCD82CEA8AB4DABC981A8115E5EB06

.. _`GitHub Downloads`: http://github.com/benoitc/gunicorn/downloads
.. _`design docs`: design.html
.. _git: http://git-scm.com/
.. _Eventlet: http://eventlet.net
.. _`here on github`: http://github.com/tilgovi/gunicorn
.. _Gevent: http://gevent.org
.. _libevent: http://monkey.org/~provos/libevent
.. _Ubuntu: http://www.ubuntu.com/
.. _PPA: https://launchpad.net/~bchesneau/+archive/gunicorn
