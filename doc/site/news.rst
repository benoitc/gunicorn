template: doc.html
title: News

_TOC_TOP_

.. contents::
    :backlinks: top

_TOC_BOT_

0.14.5 / 2012-06-24
-------------------

- fix logging during daemonisation

0.14.4 / 2012-06-24
-------------------

- new --graceful-timeout option
- fix multiple issues with request limit
- more fixes in django settings resolutions
- fix gevent.core import
- fix keepalive=0 in eventlet worker
- fix handle_error display with the unix worker
- fix tornado.wsgi.WSGIApplication calling error

- **breaking change**: take the control on graceful reload back.
  graceful can't be overrided anymore using the on_reload function.

0.14.3 / 2012-05-15
-------------------

- improvement: performance of http.body.Body.readline()
- improvement: log HTTP errors in access log like Apache
- improvment: display traceback when the worker fails to boot
- improvement: makes gunicorn work with gevent 1.0
- examples: websocket example now supports hybi13
- fix: reopen log files after initialization
- fix: websockets support
- fix: django1.4 support
- fix: only load the paster application 1 time

0.14.2 / 2012-03-16
-------------------

- add validate_class validator: allows to use a class or a method to
  initialize the app during in-code configuration
- add support for max_requests in tornado worker
- add support for disabling x_forwarded_for_header in tornado worker
- gevent_wsgi is now an alias of gevent_pywsgi
- Fix gevent_pywsgi worker

0.14.1 / 2012-03-02
-------------------

- fixing source archive, reducing its size

0.14.0 / 2012-02-27
-------------------

- check if Request line is too large: You can now pass the parameter
  ``--limit-request-line`` or set the ``limit_request_line`` in your
  configuration file to set the max size of the request line in bytes.
- limit the number of headers fields and their size. Add
  ``--limit-request-field`` and ``limit-request-field-size`` settings
- add ``p`` variable to the log access format to log pidfile
- add ``{HeaderName}o`` variable to the logo access format to log the
  response header HeaderName
- request header is now logged with the variable ``{HeaderName}i`` in the
  access log file
- improve error logging
- support logging.configFile
- support django 1.4 in both gunicorn_django & run_gunicorn command
- improve reload in django run_gunicorn command (should just work now)
- allows people to set the ``X-Forwarded-For`` header key and disable it by
  setting an empty string.
- fix support of Tornado
- many other fixes.

0.13.4 / 2011-09-23
-------------------

- fix util.closerange function used to prevent leaking fds on python 2.5
  (typo)

0.13.3 / 2011-09-19
-------------------

- refactor gevent worker
- prevent leaking fds on reexec
- fix inverted request_time computation

0.13.2 / 2011-09-17
-------------------

- Add support for Tornado 2.0 in tornado worker
- Improve access logs: allows customisation of the log format & add
  request time
- Logger module is now pluggable
- Improve graceful shutdown in Python versions >= 2.6
- Fix post_request root arity for compatibility
- Fix sendfile support
- Fix Django reloading

0.13.1 / 2011-08-22
-------------------

- Fix unix socket. log argument was missing.

0.13.0 / 2011-08-22
-------------------

- Improve logging: allows file-reopening and add access log file
  compatible with the `apache combined log format <http://httpd.apache.org/docs/2.0/logs.html#combined>`_
- Add the possibility to set custom SSL headers. X-Forwarded-Protocol
  and X-Forwarded-SSL are still the default
- New `on_reload` hook to customize how gunicorn spawn new workers on
  SIGHUP
- Handle projects with relative path in django_gunicorn command
- Preserve path parameters in PATH_INFO
- post_request hook now accepts the environ as argument.
- When stopping the arbiter, close the listener asap.
- Fix Django command `run_gunicorn` in settings reloading
- Fix Tornado_ worker exiting
- Fix the use of sendfile in wsgi.file_wrapper


0.12.2 / 2011-05-18
-------------------

- Add wsgi.file_wrapper optimised for FreeBSD, Linux & MacOSX (use
  sendfile if available)
- Fix django run_gunicorn command. Make sure we reload the application
  code.
- Fix django localisation
- Compatible with gevent 0.14dev

0.12.1 / 2011-03-23
-------------------

- Add "on_starting" hook. This hook can be used to set anything before
  the arbiter really start
- Support bdist_rpm in setup
- Improve content-length handling (pep 3333)
- Improve Django support
- Fix daemonizing (#142)
- Fix ipv6 handling

0.12.0 / 2010-12-22
-------------------

- Add support for logging configuration using a ini file.
  It uses the standard Python logging's module Configuration
  file format and allows anyone to use his custom file handler
- Add IPV6 support
- Add multidomain application example
- Improve gunicorn_django command when importing settings module
  using DJANGO_SETTINGS_MODULE environment variable
- Send appropriate error status on http parsing
- Fix pidfile, set permissions so other user can read
  it and use it.
- Fix temporary file leaking
- Fix setpgrp issue, can now be launched via ubuntu upstart
- Set the number of workers to zero on WINCH

0.11.2 / 2010-10-30
-------------------

* Add SERVER_SOFTWARE to the os.environ
* Add support for django settings environement variable
* Add support for logging configuration in Paster ini-files
* Improve arbiter notification in asynchronous workers
* Display the right error when a worker can't be used
* Fix Django support
* Fix HUP with Paster applications
* Fix readline in wsgi.input

0.11.1 / 2010-09-02
-------------------

* Implement max-requests feature to prevent memory leaks.
* Added 'worker_exit' server hook.
* Reseed the random number generator after fork().
* Improve Eventlet worker.
* Fix Django command `run_gunicorn`.
* Fix the default proc name internal setting.
* Workaround to prevent Gevent worker to segfault on MacOSX.

0.11.0 / 2010-08-12
-------------------

* Improve dramatically performances of Gevent and Eventlet workers
* Optimize HTTP parsing
* Drop Server and Date headers in start_response when provided.
* Fix latency issue in async workers

0.10.1 / 2010-08-06
-------------------

* Improve gevent's workers. Add "egg:gunicorn#gevent_wsgi" worker using
  `gevent.wsgi <http://www.gevent.org/gevent.wsgi.html>`_ and
  "egg:gunicorn#gevent_pywsgi" worker using `gevent.pywsgi
  <http://www.gevent.org/gevent.pywsgi.html>`_ .
  **"egg:gunicorn#gevent"** using our own HTTP parser is still here and
  is **recommended** for normal uses. Use the "gevent.wsgi" parser if you
  need really fast connections and don't need streaming, keepalive or ssl.
* Add pre/post request hooks
* Exit more quietly
* Fix gevent dns issue

0.10.0 / 2010-07-08
-------------------

* New HTTP parser.
* New HUP behaviour. Re-reads the configuration and then reloads all
  worker processes without changing the master process id. Helpful for
  code reloading and monitoring applications like supervisord and runit.
* Added a preload configuration parameter. By default, application code
  is now loaded after a worker forks. This couple with the new HUP
  handling can be used for dev servers to do hot code reloading. Using
  the preload flag can help a bit in small memory VM's.
* Allow people to pass command line arguments to WSGI applications. See:
  `examples/alt_spec.py
  <http://github.com/benoitc/gunicorn/raw/master/examples/alt_spec.py>`_
* Added an example gevent reloader configuration:
  `examples/example_gevent_reloader.py
  <http://github.com/benoitc/gunicorn/blob/master/examples/example_gevent_reloader.py>`_.
* New gevent worker "egg:gunicorn#gevent2", working with gevent.wsgi.
* Internal refactoring and various bug fixes.
* New documentation website.

0.9.1 / 2010-05-26
------------------

* Support https via X-Forwarded-Protocol or X-Forwarded-Ssl headers
* Fix configuration
* Remove -d options which was used instead of -D for daemon.
* Fix umask in unix socket

0.9.0 / 2010-05-24
------------------

* Added *when_ready* hook. Called just after the server is started
* Added *preload* setting. Load application code before the worker processes
  are forked.
* Refactored Config
* Fix pidfile
* Fix QUIT/HUP in async workers
* Fix reexec
* Documentation improvements

0.8.1 / 2010-04-29
------------------

* Fix builtins import in config
* Fix installation with pip
* Fix Tornado WSGI support
* Delay application loading until after processing all configuration

0.8.0 / 2010-04-22
------------------

* Refactored Worker management for better async support. Now use the -k option
  to set the type of request processing to use
* Added support for Tornado_


0.7.2 / 2010-04-15
------------------

* Added --spew option to help debugging (installs a system trace hook)
* Some fixes in async arbiters
* Fix a bug in start_response on error

0.7.1 / 2010-04-01
------------------

* Fix bug when responses have no body.

0.7.0 / 2010-03-26
------------------

* Added support for Eventlet_ and Gevent_ based workers.
* Added Websockets_ support
* Fix Chunked Encoding
* Fix SIGWINCH on OpenBSD_
* Fix `PEP 333`_ compliance for the write callable.

0.6.5 / 2010-03-11
------------------

* Fix pidfile handling
* Fix Exception Error

0.6.4 / 2010-03-08
------------------

* Use cStringIO for performance when possible.
* Fix worker freeze when a remote connection closes unexpectedly.

0.6.3 / 2010-03-07
------------------

* Make HTTP parsing faster.
* Various bug fixes

0.6.2 / 2010-03-01
------------------

* Added support for chunked response.
* Added proc_name option to the config file.
* Improved the HTTP parser. It now uses buffers instead of strings to store
  temporary data.
* Improved performance when sending responses.
* Workers are now murdered by age (the oldest is killed first).


0.6.1 / 2010-02-24
------------------

* Added gunicorn config file support for Django admin command
* Fix gunicorn config file. -c was broken.
* Removed TTIN/TTOU from workers which blocked other signals.

0.6 / 2010-02-22
------------------

* Added setproctitle support
* Change privilege switch behavior. We now work like NGINX, master keeps the
  permissions, new uid/gid permissions are only set for workers.

0.5.1 / 2010-02-22
------------------

* Fix umask
* Added Debian packaging

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
* Better support of Paste-compatible applications
* Some refactoring to make the code easier to hack
* Allow multiple keys in request and response headers

.. _Tornado: http://www.tornadoweb.org/
.. _`PEP 333`: http://www.python.org/dev/peps/pep-0333/
.. _Eventlet: http://eventlet.net
.. _Gevent: http://gevent.org
.. _OpenBSD: http://openbsd.org
.. _Websockets: http://dev.w3.org/html5/websockets/
