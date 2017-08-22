=========
Changelog
=========

19.8.0 / not released
=====================

- :pr:`1569`, :pr:`1418` and :issue:`1338`: The ``gaiohttp`` worker is
  deprecated. See the :ref:`worker-class` documentation for more information.

19.7.1 / 2017/03/21
===================

- fix: continue if SO_REUSEPORT seems to be available but fails (:issue:`1480`)
- fix: support non-decimal values for the umask command line option (:issue:`1325`)

19.7.0 / 2017/03/01
===================

- The previously deprecated ``gunicorn_django`` command has been removed.
  Use the :ref:`gunicorn-cmd` command-line interface instead.
- The previously deprecated ``django_settings`` setting has been removed.
  Use the :ref:`raw-env` setting instead.
- The default value of :ref:`ssl-version` has been changed from
  ``ssl.PROTOCOL_TLSv1`` to ``ssl.PROTOCOL_SSLv23``.
- fix: initialize the group access list when initgroups is set (:issue:`1297`)
- add environment variables to gunicorn access log format (:issue:`1291`)
- add --paste-global-conf option (:issue:`1304`)
- fix: print access logs to STDOUT (:issue:`1184`)
- remove upper limit on max header size config (:issue:`1313`)
- fix: print original exception on AppImportError (:issue:`1334`)
- use SO_REUSEPORT if available (:issue:`1344`)
- `fix leak <https://github.com/benoitc/gunicorn/commit/b4c41481e2d5ef127199a4601417a6819053c3fd>`_ of duplicate file descriptor for bound sockets.
- add --reload-engine option, support inotify and other backends (:issue:`1368`, :issue:`1459`)
- fix: reject request with invalid HTTP versions
- add ``child_exit`` callback (:issue:`1394`)
- add support for eventlets _AlreadyHandled object (:issue:`1406`)
- format boot tracebacks properly with reloader (:issue:`1408`)
- refactor socket activation and fd inheritance for better support of SystemD (:issue:`1310`)
- fix: o fds are given by default in gunicorn (:issue:`1423`)
- add ability to pass settings to GUNICORN_CMD_ARGS environnement variable which helps in container world (:issue:`1385`)
- fix:  catch access denied to pid file (:issue:`1091`)
-  many additions and improvements to the documentation

Breaking Change
+++++++++++++++

- **Python 2.6.0** is the last supported version

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
