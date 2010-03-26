template: index.html

Green Unicorn
=============

Green Unicorn (gunicorn) is an HTTP/WSGI Server for UNIX designed to serve
`fast clients`_ or `sleepy applications`_.

This is a port of Unicorn_ in Python. Meet us on the `#gunicorn IRC channel`_
on Freenode_.

Gunicorn is released under the MIT License. See the LICENSE_ for more details.

Features
--------

- Designed for Unix, WSGI_, fast clients and sleepy applications.
- Compatible with Python 2.x (>= 2.5)
- Easy integration with Django_ and Paster_ compatible applications
  (`Pylons`_, `TurboGears 2`_, ...)
- Process management: Gunicorn_ reaps and restarts workers that die.
- Load balancing via pre-fork and a shared socket
- Graceful worker process restarts
- Upgrade "àla nginx" without losing connections
- Simple and easy Python configuration
- Decode chunked transfers on-the-fly, allowing upload progress notifications
  or stream-based protocols over HTTP
- Support for `Eventlet`_ and `Gevent`_ .
- Post- and pre-fork hooks

Applications
------------

* Any WSGI_, Django_ and Paster_ compatible applications
  (`Pylons`_, `TurboGears 2`_, ...)
* Websockets (see the example_ or the screencast_)
* Reverse proxy implementation (with `Restkit WSGI proxy`_)
* Comet
* Long Polling

.. _WSGI:  http://www.python.org/dev/peps/pep-0333/
.. _`fast clients`: faq.html
.. _`sleepy applications`: faq.html
.. _Unicorn: http://unicorn.bogomips.org/
.. _`#gunicorn IRC channel`: http://webchat.freenode.net/?channels=gunicorn
.. _Freenode: http://freenode.net
.. _LICENSE: http://github.com/benoitc/gunicorn/blob/master/LICENSE
.. _Gunicorn: http://gunicorn.org
.. _Django: http://djangoproject.com
.. _Paster: http://pythonpaste.org/
.. _Eventlet: http://eventlet.net
.. _Gevent: http://gevent.org
.. _Pylons: http://pylonshq.com/
.. _Turbogears 2: http://turbogears.org/2.0/
.. _example: http://github.com/benoitc/gunicorn/blob/master/examples/websocket.py
.. _`Restkit WSGI proxy`: http://benoitc.github.com/restkit/wsgi_proxy.html
.. _screencast: http://vimeo.com/10461162
