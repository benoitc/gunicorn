Gunicorn
========

.. image:: https://img.shields.io/pypi/v/gunicorn.svg?style=flat
    :alt: PyPI version
    :target: https://pypi.python.org/pypi/gunicorn

.. image:: https://img.shields.io/pypi/pyversions/gunicorn.svg
    :alt: Supported Python versions
    :target: https://pypi.python.org/pypi/gunicorn

.. image:: https://github.com/benoitc/gunicorn/actions/workflows/tox.yml/badge.svg
    :alt: Build Status
    :target: https://github.com/benoitc/gunicorn/actions/workflows/tox.yml

Gunicorn 'Green Unicorn' is a Python WSGI HTTP Server for UNIX. It's a pre-fork
worker model ported from Ruby's Unicorn_ project. The Gunicorn server is broadly
compatible with various web frameworks, simply implemented, light on server
resource usage, and fairly speedy.

**New in v24**: Native ASGI support (beta) for async frameworks like FastAPI!

Quick Start
-----------

.. code-block:: bash

    pip install gunicorn
    gunicorn myapp:app --workers 4

For ASGI applications (FastAPI, Starlette):

.. code-block:: bash

    gunicorn myapp:app --worker-class asgi

Features
--------

- WSGI support for Django, Flask, Pyramid, and any WSGI framework
- **ASGI support** (beta) for FastAPI, Starlette, Quart
- uWSGI binary protocol for nginx integration
- Multiple worker types: sync, gthread, gevent, eventlet, asgi
- Graceful worker process management
- Compatible with Python 3.12+

Documentation
-------------

Full documentation at https://gunicorn.org

- `Quickstart <https://gunicorn.org/quickstart/>`_
- `Configuration <https://gunicorn.org/configure/>`_
- `Deployment <https://gunicorn.org/deploy/>`_
- `Settings Reference <https://gunicorn.org/reference/settings/>`_

Community
---------

- Report bugs on `GitHub Issues <https://github.com/benoitc/gunicorn/issues>`_
- Chat in `#gunicorn`_ on `Libera.chat`_
- See `CONTRIBUTING.md <CONTRIBUTING.md>`_ for contribution guidelines

License
-------

Gunicorn is released under the MIT License. See the LICENSE_ file for details.

.. _Unicorn: https://bogomips.org/unicorn/
.. _`#gunicorn`: https://web.libera.chat/?channels=#gunicorn
.. _`Libera.chat`: https://libera.chat/
.. _LICENSE: https://github.com/benoitc/gunicorn/blob/master/LICENSE
