template: doc.html
title: Installing Gunicorn


This is a manual for installing Gunicorn and its dependencies.

Installing Gunicorn
=====================

Gunicorn requires **Python 2.x superior to 2.5** to work. Python 3.x will be supported soon. 

Installing with easy_install
++++++++++++++++++++++++++++

To install Gunicorn using easy_install you must make sure you have a recent version of setuptools installed (as of this writing, 0.6c6 (0.6a9 on windows) or later)::

  $ curl -O http://peak.telecommunity.com/dist/ez_setup.py
  $ sudo python ez_setup.py -U setuptools

To install or upgrade to the latest released version of Gunicorn::

  $ sudo easy_install -U gunicorn

Installing from source
----------------------

To install Gunicorn from source, simply use the normal procedure for installing any Python package. Since Gunicorn uses setuptools, all dependencies (including setuptools itself) will be automatically acquired and installed for you as appropriate.

Fetch sources
+++++++++++++

You could download latest sources from `Github Downloads <http://github.com/benoitc/gunicorn/downloads>`_

Or fetch them with git. Therefore we have to `install git <http://git-scm.com/>`_ and then run::

  $ git clone git://github.com/benoitc/gunicorn.git

Install Gunicorn
++++++++++++++++

::

  $ python setup.py install

If you're using a git clone, it's recommended to use the setuptools `develop` command, which will simply activate Gunicorn directly from your source directory. This way you can do a hg fetch or make changes to the source code without re-installing every time::

  $ python setup.py develop
