Gunicorn
--------

.. image:: https://img.shields.io/pypi/v/gunicorn.svg?style=flat
    :alt: PyPI version
    :target: https://pypi.python.org/pypi/gunicorn

.. image:: https://img.shields.io/pypi/pyversions/gunicorn.svg
    :alt: Supported Python versions
    :target: https://pypi.python.org/pypi/gunicorn

.. image:: https://travis-ci.org/benoitc/gunicorn.svg?branch=master
    :alt: Build Status
    :target: https://travis-ci.org/benoitc/gunicorn

Gunicorn 'Green Unicorn' is a Python WSGI HTTP Server for UNIX. It's a pre-fork
worker model ported from Ruby's Unicorn_ project. The Gunicorn server is broadly
compatible with various web frameworks, simply implemented, light on server
resource usage, and fairly speedy.

Feel free to join us in `#gunicorn`_ on Freenode_.

Documentation
-------------

The documentation is hosted at http://docs.gunicorn.org.

Installation
------------

Gunicorn requires **Python 2.x >= 2.6** or **Python 3.x >= 3.2**.

Install from PyPI::

    $ pip install gunicorn


Usage
-----

Basic usage::

    $ gunicorn [OPTIONS] APP_MODULE

Where ``APP_MODULE`` is of the pattern ``$(MODULE_NAME):$(VARIABLE_NAME)``. The
module name can be a full dotted path. The variable name refers to a WSGI
callable that should be found in the specified module.

Example with test app::

    $ cd examples
    $ gunicorn --workers=2 test:app


License
-------

Gunicorn is released under the MIT License. See the LICENSE_ file for more
details.

.. _Unicorn: https://bogomips.org/unicorn/
.. _`#gunicorn`: https://webchat.freenode.net/?channels=gunicorn
.. _Freenode: https://freenode.net/
.. _LICENSE: https://github.com/benoitc/gunicorn/blob/master/LICENSE
