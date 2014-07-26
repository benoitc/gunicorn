Changelog
=========

19.1 / 2014-07-26 
~~~~~~~~~~~~~~~~~

Changes
-------

Core
++++

- fix `#785 <https://github.com/benoitc/gunicorn/issues/785>`_: handle binary type address given to a client socket address
- fix graceful shutdown. make sure QUIT and TERMS signals are switched
  everywhere.
- support loading config from module (`#799 <https://github.com/benoitc/gunicorn/issues/799>`_)
- fix check for file-like objects (`#805 <https://github.com/benoitc/gunicorn/issues/805>`_)
- fix `#815 <https://github.com/benoitc/gunicorn/issues/815>`_  args validation in WSGIApplication.init
- fix `#787 <https://github.com/benoitc/gunicorn/issues/787>`_ check if we load a pyc file or not.


Tornado worker
++++++++++++++


- fix `#771 <https://github.com/benoitc/gunicorn/issues/771>`_: support tornado 4.0
- fix #783: x_headers error. The x-forwarded-headers option has been removed
  in `c4873681299212d6082cd9902740eef18c2f14f1
  <https://github.com/benoitc/gunicorn/commit/c4873681299212d6082cd9902740eef18c2f14f1>`_. The discussion is
  available on `#633 <https://github.com/benoitc/gunicorn/pull/633>`_.

AioHttp worker
++++++++++++++

- fix: fetch all body in input. fix `#803 <https://github.com/benoitc/gunicorn/issues/803>`_
- fix: don't install the worker if python < 3.3
- fix  `#822 <https://github.com/benoitc/gunicorn/issues/822>`_: Support UNIX sockets in gaiohttp worker


Async worker
++++++++++++

- fix `#790 <https://github.com/benoitc/gunicorn/issues/790>`_ StopIteration shouldn't be catched at this level.

Logging
+++++++

- add statsd logging handler fix `#748 <https://github.com/benoitc/gunicorn/issues/748>`_

Paster
++++++

- fix `#809 <https://github.com/benoitc/gunicorn/issues/809>`_ Set global logging configuration from a Paste config.

Extra
+++++

- fix RuntimeError in gunicorn.reloader (`#807 <https://github.com/benoitc/gunicorn/issues/807>`_)

Documentation
+++++++++++++

- update faq: put a note on how `watch logs in the console
  <http://docs.gunicorn.org/en/latest/faq.html#why-i-don-t-see-any-logs-in-the-console>`_
  since many people asked for it.

19.0 / 2014-06-12
~~~~~~~~~~~~~~~~~

Gunicorn 19.0 is a major release with new features and fixes. This
version improve a lot the usage of Gunicorn with python 3 by adding `two
new workers <http://docs.gunicorn.org/en/latest/design.html#asyncio-workers>`_ to it: `gthread` a fully threaded async worker using futures
and `gaiohttp` a worker using asyncio.


Breaking Changes
----------------

Switch QUIT and TERM signals
++++++++++++++++++++++++++++

With this change, when gunicorn receives a QUIT all the workers are
killed immediately and exit and TERM is used for the graceful shutdown.

Note: the old behaviour was based on the NGINX but the new one is more
correct according the following doc:

https://www.gnu.org/software/libc/manual/html_node/Termination-Signals.html

also it is complying with the way the signals are sent by heroku:

https://devcenter.heroku.com/articles/python-faq#what-constraints-exist-when-developing-applications-on-heroku

Deprecations
+++++++++++++

`run_gunicorn`, `gunicorn_django` and `gunicorn_paster` are now
completely deprecated and will be removed in the next release. Use the
`gunicorn` command instead.


Changes:
--------

core
++++

- add aiohttp worker named `gaiohttp` using asyncio. Full async worker
  on python 3.
- fix HTTP-violating excess whitespace in write_error output
- fix: try to log what happened in the worker after a timeout, add a
  `worker_abort` hook on SIGABRT signal.
- fix: save listener socket name in workers so we can handle buffered
  keep-alive requests after the listener has closed.
- add on_exit hook called just before exiting gunicorn.
- add support for python 3.4
- fix: do not swallow unexpected errors when reaping
- fix: remove incompatible SSL option with python 2.6
- add new async gthread worker and `--threads` options allows to set multiple
  threads to listen on connection
- deprecate `gunicorn_django` and `gunicorn_paster`
- switch QUIT and TERM signal
- reap workers in SIGCHLD handler
- add universal wheel support
- use `email.utils.formatdate` in gunicorn.util.http_date
- deprecate the `--debug` option
- fix: log exceptions that occur after response start …
- allows loading of applications from `.pyc` files (#693)
- fix: issue #691, raw_env config file parsing
- use a dynamic timeout to wait for the optimal time. (Reduce power
  usage)
- fix python3 support when notifying the arbiter
- add: honor $WEB_CONCURRENCY environment variable. Useful for heroku
  setups.
- add: include tz offset in access log
- add: include access logs in the syslog handler.
- add --reload option for code reloading
- add the capability to load `gunicorn.base.Application` without the loading of
  the arguments of the command line. It allows you to :ref:`embed gunicorn in
  your own application <custom>`.
- improve: set wsgi.multithread to True for async workers
- fix logging: make sure to redirect wsgi.errors when needed
- add: syslog logging can now be done to a unix socket
- fix logging: don't try to redirect stdout/stderr to the logfile.
- fix logging: don't propagate log
- improve logging: file option can be overriden by the gunicorn options
  `--error-logfile` and `--access-logfile` if they are given.
- fix: dont' override SERVER_* by the Host header
- fix: handle_error
- add more option to configure SSL
- fix: sendfile with SSL
- add: worker_int callback (to react on SIGTERM)
- fix: don't depend on entry point for internal classes, now absolute
  modules path can be given.
- fix: Error messages are now encoded in latin1
- fix: request line length check
- improvement: proxy_allow_ips: Allow proxy protocol if "*" specified
- fix: run worker's `setup` method  before setting num_workers
- fix: FileWrapper inherit from `object` now
- fix: Error messages are now encoded in latin1
- fix: don't spam the console on SIGWINCH.
- fix: logging -don't stringify T and D logging atoms (#621)
- add support for the latest django version
- deprecate `run_gunicorn` django option
- fix: sys imported twice


gevent worker
+++++++++++++

- fix: make sure to stop all listeners
- fix: monkey patching is now done in the worker
- fix: "global name 'hub' is not defined"
- fix: reinit `hub` on old versions of gevent
- support gevent 1.0
- fix: add subprocess in monket patching
- fix: add support for multiple listener

eventlet worker
+++++++++++++++

- fix: merge duplicate EventletWorker.init_process method (fixes #657)
- fix: missing errno import for eventlet sendfile patch
- fix: add support for multiple listener

tornado worker
++++++++++++++

- add gracefull stop support

18.0 / 2013-08-26
~~~~~~~~~~~~~~~~~

- new: add ``-e/--env`` command line argument to pass an environment variables to
  gunicorn
- new: add ``--chdir`` command line argument to specified directory
  before apps loading.  - new: add wsgi.file_wrapper support in async workers
- new: add ``--paste`` command line argument to set the paster config file
- deprecated: the command ``gunicorn_django`` is now deprecated. You should now
  run your application with the WSGI interface installed with your project (see
  https://docs.djangoproject.com/en/1.4/howto/deployment/wsgi/gunicorn/) for
  more infos.
- deprecated:  the command ``gunicorn_paste`` is deprecated. You now should use
  the new ``--paste`` argument to set the configuration file of your paster
  application.
- fix: Removes unmatched leading quote from the beginning of the default access
  log format string
- fix: null timeout
- fix: gevent worker
- fix: don't reload the paster app when using pserve
- fix: after closing for error do not keep alive the connection
- fix: responses 1xx, 204 and 304 should not force the connection to be closed


History
=======

.. toctree::
   :titlesonly:

   2014-news
   2013-news
   2012-news
   2011-news
   2010-news
