=========
Changelog
=========

19.3.0 / 2015/03/06
===================

Changes
-------

Core
++++

- fix: :issue:`978` make sure a listener is inheritable
- add `check_config` class method to workers
- fix: :issue:`983` fix select timeout in sync worker with multiple
  connections
- allows workers to access to the reloader. close :issue:`984`
- raise TypeError instead of AssertionError

Logging
+++++++

- make Logger.loglevel a classs attribute

Documentation
+++++++++++++

- fix: :issue:`988` fix syntax errors in examples/gunicorn_rc

19.2.1 / 2015/02/4
==================

Changes
-------

Logging
+++++++

- expose loglevel in the Logger class

AsyncIO worker (gaiohttp)
+++++++++++++++++++++++++

- fix :issue:`977` fix initial crash

Documentation
+++++++++++++

- document security mailing-list in the contributing page.


19.2 / 2015/01/30
=================

Changes
-------

Core
++++

- optimize the sync workers when listening on a single interface
- add `--sendfile` settings to enable/disable sendfile. fix :issue:`856` .
- add the selectors module to the code base. :issue:`886`
- fix :pr:`862` add `--max-requests-jitter` setting to set the maximum jitter to add to the
  max-requests setting.
- fix :issue:`899` propagate proxy_protocol_info to keep-alive requests
- fix :issue:`863` worker timeout: dynamic timeout has been removed, fix a race
  condition error
- fix: Avoid world writable file
- fix :issue:`917`: the deprecated ``--debug`` option has been removed.

Logging
+++++++

- fix :issue:`941`  set logconfig default to paster more trivially
- add statsd-prefix config setting: set the prefix to use when emitting statsd
  metrics
- :issue:`832` log to console by default
- fix :issue:`845`: set the gunicorn loggers from the paste config

Thread Worker
+++++++++++++

- fix :issue:`908` make sure the worker can continue to accept requests

Eventlet Worker
+++++++++++++++

- fix :issue:`867` Fix eventlet shutdown to actively shut down the workers.

Documentation
+++++++++++++

Many improvements and fixes have been done, see the detailled changelog for
more informations.

History
=======

.. toctree::
   :titlesonly:

   2015-news
   2014-news
   2013-news
   2012-news
   2011-news
   2010-news
