template: doc.html
title: Installing Gunicorn

Installation
============

Requirements
------------

- **Python 2.5 or newer** (Python 3.x will be supported soon)
- setuptools >= 0.6c6
- nosetests (for the test suite only)

Installing with easy_install
----------------------------

If you don't already have ``easy_install`` available you'll want to download and run the ``ez_setup.py`` script::

  $ curl -O http://peak.telecommunity.com/dist/ez_setup.py
  $ sudo python ez_setup.py -U setuptools

To install or upgrade to the latest released version of Gunicorn::

  $ sudo easy_install -U gunicorn

Installing from source
----------------------

You can install Gunicorn from source as simply as you would install any other Python package. Gunicorn uses setuptools which will automatically fetch all dependencies (including setuptools itself).

Get a Copy
++++++++++

You can download a tarball of the latest sources from `GitHub Downloads`_ or fetch them with git_::

    $ git clone git://github.com/benoitc/gunicorn.git

.. _`GitHub Downloads`: http://github.com/benoitc/gunicorn/downloads
.. _git: http://git-scm.com/

Installation
++++++++++++++++

::

  $ python setup.py install

If you've cloned the git repository, its highly recommended that you use the ``develop`` command which will allow you to use Gunicorn from the source directory. This will allow you to keep up to date with development on GitHub as well as make changes to the source::

  $ python setup.py develop
  
Installing on Ubuntu/Debian systems
-----------------------------------

If you use `ubuntu <http://www.ubuntu.com/>`_ karmic, you can update your system with packages from our `PPA <https://launchpad.net/~bchesneau/+archive/gunicorn>`_ by adding ppa:bchesneau/gunicorn  to your system's Software Sources.

Or this PPA can be added to your system manually by copying the lines below and adding them to your system's software sources::

  deb http://ppa.launchpad.net/bchesneau/gunicorn/ubuntu karmic main 
  deb-src http://ppa.launchpad.net/bchesneau/gunicorn/ubuntu karmic main
  
Signing key::

  1024R/15E5EB06
  
Fingerprint::

  49AEEDFF5CDCD82CEA8AB4DABC981A8115E5EB06
