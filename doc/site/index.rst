template: index.html

Green Unicorn
=============

gunicorn 'Green Unicorn' is a WSGI HTTP Server for UNIX, fast clients and nothing else.

This is a port of Unicorn (http://unicorn.bogomips.org/) in Python. Meet us on `#gunicorn irc channel <http://webchat.freenode.net/?channels=gunicorn>`_ on `Freenode`_.

Gunicorn is under MIT License. see `LICENSE <http://github.com/benoitc/gunicorn/blob/master/LICENSE>`_ file for more details.

Features
--------

- Designed for WSGI, Unix and fast clients.
- Compatible with Python 2.x superior to 2.5
- Easy integration with `Django <http://djangoproject.com>`_ and `Paster <http://pythonpaste.org/>`_ compatible applications (Pylons, Turbogears 2, ...)
- Process management: `Gunicorn`_ reap and restart workers that die.
- Load balancing done by the os
- Graceful restart of workers
- Upgrade "àla nginx" without losing connections
- Simple and easy Python DSL for configuration
- Decode chunked transfers on-the-fly, allowing upload progress notifications or
  stream-based protocols over HTTP.

.. _freenode: http://freenode.net
.. _Gunicorn: http://gunicorn.org
