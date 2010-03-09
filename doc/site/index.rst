template: index.html

Green Unicorn
=============

Green Unicorn (gunicorn) is an HTTP/WSGI Server for UNIX designed to serve `fast clients`_ and nothing else.

This is a port of Unicorn_ in Python. Meet us on the `#gunicorn IRC channel`_  on Freenode_.

Gunicorn is released under the MIT License. See the LICENSE_ for more details.

Features
--------

- Designed for Unix, WSGI, and fast clients
- Compatible with Python 2.x (>= 2.5)
- Easy integration with Django_ and Paster_ compatible applications (Pylons, TurboGears 2, ...)
- Process management: Gunicorn_ reaps and restarts workers that die.
- Load balancing via pre-fork and a shared socket
- Graceful worker process restarts
- Upgrade "àla nginx" without losing connections
- Simple and easy Python configuration
- Decode chunked transfers on-the-fly, allowing upload progress notifications or
  stream-based protocols over HTTP
- Post- and pre-fork hooks

.. _`fast clients`: faq.html
.. _Unicorn: http://unicorn.bogomips.org/
.. _`#gunicorn IRC channel`: http://webchat.freenode.net/?channels=gunicorn
.. _Freenode: http://freenode.net
.. _LICENSE: http://github.com/benoitc/gunicorn/blob/master/LICENSE
.. _Gunicorn: http://gunicorn.org
.. _Django: http://djangoproject.com
.. _Paster: http://pythonpaste.org/