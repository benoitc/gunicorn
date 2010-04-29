template: doc.html
title: News

News
====

0.8.1 / 2010-04-29
------------------

- Fix builtins import in config
- Fix installation with pip
- Fix Tornado worker

0.8.0 / 2010-04-22
------------------

- Refactored Worker management for better async support. Now use the -k option to set the type of request processing to use
- Added support for `Tornado <http://www.tornadoweb.org/>`_ 


0.7.2 / 2010-04-15
------------------

- Added --spew option to help debugging (install a Trace hook)
- Some fixes in async arbiters
- Fix a bug in start_response on error

0.7.1 / 2010-04-01
------------------

- Fix bug when responses have no body.

0.7.0 / 2010-03-26
------------------

- Added support for `sleepy applications <faq.html>`_ using Eventlet_ or Gevent_.
- Added Websockets_ support
- Fix Chunked Encoding
- Fix SIGWINCH on OpenBSD_
- Fix `PEP 333 <http://www.python.org/dev/peps/pep-0333/>`_ compliance for the write callable.

0.6.5 / 2010-03-11
------------------

- Fix pidfile
- Fix Exception Error

0.6.4 / 2010-03-08
------------------

- Use cStringIO for performance when possible.
- Fix worker freeze when a remote connection closes unexpectedly.

0.6.3 / 2010-03-07
------------------

* Make HTTP parsing faster.
* Some fixes (see `logs <http://github.com/benoitc/gunicorn/commits/master>`_)

0.6.2 / 2010-03-01
------------------

* Added support for chunked response.
* Added proc_name option to the config file.
* Improved the HTTP parser. It now uses buffers instead of strings to store temporary data.
* Improved performance when sending responses.
* Workers are now murdered by age (the oldest is killed first).


0.6.1 / 2010-02-24
------------------

* Added gunicorn config file support for django admin command
* Fix gunicorn config file. -c was broken.
* Removed TTIN/TTOU from workers which blocked other signals.

0.6 / 2010-02-22
------------------

* Added setproctitle
* Change privilege switch behaviour. We now work like NGINX, master keeps the permissions, new uid/gid permissions are only set for workers.

0.5.1 / 2010-02-22
------------------

* Fix umask
* Added debian packaging

0.5 / 2010-02-20 
----------------

* Added `configuration file <configuration.html>`_ handler.
* Added support for pre/post fork hooks
* Added support for before_exec hook
* Added support for unix sockets
* Added launch of workers processes under different user/group
* Added umask option
* Added SCRIPT_NAME support
* Better support of some exotic settings for Django projects
* Better support of Paste-compatible applicatins
* Some refactoring to make the code easier to hack
* Allow multiple keys in request and response headers

.. _Eventlet: http://eventlet.net
.. _Gevent: http://gevent.org
.. _OpenBSD: http://openbsd.org
.. _Websockets: http://dev.w3.org/html5/websockets/
