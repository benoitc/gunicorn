=========
Changelog
=========

19.9.0 / 2018/07/03
===================

- fix: address a regression that prevented syslog support from working
  (:issue:`1668`, :pr:`1773`)
- fix: correctly set `REMOTE_ADDR` on versions of Python 3 affected by
  `Python Issue 30205 <https://bugs.python.org/issue30205>`_
  (:issue:`1755`, :pr:`1796`)
- fix: show zero response length correctly in access log (:pr:`1787`)
- fix: prevent raising :exc:`AttributeError` when ``--reload`` is not passed
  in case of a :exc:`SyntaxError` raised from the WSGI application.
  (:issue:`1805`, :pr:`1806`)
- The internal module ``gunicorn.workers.async`` was renamed to ``gunicorn.workers.base_async``
  since ``async`` is now a reserved word in Python 3.7.
  (:pr:`1527`)

19.8.1 / 2018/04/30
===================

- fix: secure scheme headers when bound to a unix socket
  (:issue:`1766`, :pr:`1767`)

19.8.0 / 2018/04/28
===================

- Eventlet 0.21.0 support (:issue:`1584`)
- Tornado 5 support (:issue:`1728`, :pr:`1752`)
- support watching additional files with ``--reload-extra-file``
  (:pr:`1527`)
- support configuring logging with a dictionary with ``--logging-config-dict``
  (:issue:`1087`, :pr:`1110`, :pr:`1602`)
- add support for the ``--config`` flag in the ``GUNICORN_CMD_ARGS`` environment
  variable (:issue:`1576`, :pr:`1581`)
- disable ``SO_REUSEPORT`` by default and add the ``--reuse-port`` setting
  (:issue:`1553`, :issue:`1603`, :pr:`1669`)
- fix: installing `inotify` on MacOS no longer breaks the reloader
  (:issue:`1540`, :pr:`1541`)
- fix: do not throw ``TypeError`` when ``SO_REUSEPORT`` is not available
  (:issue:`1501`, :pr:`1491`)
- fix: properly decode HTTP paths containing certain non-ASCII characters
  (:issue:`1577`, :pr:`1578`)
- fix: remove whitespace when logging header values under gevent (:pr:`1607`)
- fix: close unlinked temporary files (:issue:`1327`, :pr:`1428`)
- fix: parse ``--umask=0`` correctly (:issue:`1622`, :pr:`1632`)
- fix: allow loading applications using relative file paths
  (:issue:`1349`, :pr:`1481`)
- fix: force blocking mode on the gevent sockets (:issue:`880`, :pr:`1616`)
- fix: preserve leading `/` in request path (:issue:`1512`, :pr:`1511`)
- fix: forbid contradictory secure scheme headers
- fix: handle malformed basic authentication headers in access log
  (:issue:`1683`, :pr:`1684`)
- fix: defer handling of ``USR1`` signal to a new greenlet under gevent
  (:issue:`1645`, :pr:`1651`)
- fix: the threaded worker would sometimes close the wrong keep-alive
  connection under Python 2 (:issue:`1698`, :pr:`1699`)
- fix: re-open log files on ``USR1`` signal using ``handler._open`` to
  support subclasses of ``FileHandler`` (:issue:`1739`, :pr:`1742`)
- deprecation: the ``gaiohttp`` worker is deprecated, see the
  :ref:`worker-class` documentation for more information
  (:issue:`1338`, :pr:`1418`, :pr:`1569`)


History
=======

.. toctree::
   :titlesonly:

   2017-news
   2016-news
   2015-news
   2014-news
   2013-news
   2012-news
   2011-news
   2010-news
