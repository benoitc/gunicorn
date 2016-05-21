=========
Changelog
=========

19.6.0 / 2016/05/21
===================

Core & Logging
++++++++++++++

- improvement of the binary upgrade behaviour using USR2: remove file lockin (:issue:`1270`)
- add the ``--capture-output`` setting to capture stdout/stderr tot the log
file (:issue:`1271`)
- Allow disabling ``sendfile()`` via the `SENDFILE`` environment variable
(:issue:`1252`
- fix reload under pycharm (:issue:`1129`)

Workers
+++++++

- fix: make sure to remove the signal from the worker pipe (:issue:`1269`)
- fix: **gthread** worker, handle removed socket in the select loop
(:issue:`1258`)

19.5.0 / 2016/05/10
===================

Core
++++

- fix: Ensure response to HEAD request won't have message body  
- fix: lock domain socket and remove on last arbiter exit (:issue:`#1220`)
- improvement: use EnvironmentError instead of socket.error (:issue:`939`)
- add: new $FORWARDDED_ALLOW_IPS environment variable (:issue:`1205`)
- fix: infinite recursion when destroying sockets (:issue:`1219`)
- fix: close sockets on shutdown (:issue:`922`)
- fix: clean up sys.exc_info calls to drop circular refs (:issue:`1228`)
- fix: do post_worker_init after load_wsgi (:issue:`1248`)

Workers
+++++++

- fix access logging in gaiohttp worker (:issue:`#1193`)
- eventlet: handle QUIT in a new coroutine (:issue:`#1217`)
- gevent: remove obsolete exception clauses in run (:issue:`#1218`)
- tornado: fix extra "Server" response header (:issue:`1246`)
- fix: unblock the wait loop under python 3.5 in sync worker (:issue:`1256`)

Logging
+++++++

- fix: log message for listener reloading (:issue:`1181`)
- Let logging module handle traceback printing (:issue:`1201`)
- improvement:  Allow configuring logger_class with statsd_host (:issue:`#1188`)
- fix: traceback formatting (:issue:`1235`)
- fix: print error logs on stderr and access logs on stdout (:issue:`1184`)


Documentation
+++++++++++++

- Simplify installation instructions in gunicorn.org (:issue:`1072`)
- Fix URL and default worker type in example_config (:issue:`1209`)
- update django doc url to 1.8 lts (:issue:`1213`)
- fix: miscellaneous wording corrections (:issue:`1216`)
- Add PSF License Agreement of selectors.py to NOTICE (:issue: `1226`)
- document LOGGING overriding (:issue:`1051`)
- put a note that error logs are only errors from Gunicorn (:issue:`1124`)
- add a note about the requirements of the threads workers under python 2.x (:issue:`1200`)
- add access_log_format to config example (:issue:`1251`)

Tests
+++++

- Use more pytest.raises() in test_http.py

19.4.5 / 2016/01/05
===================

- fix: NameError fileno in gunicorn.http.wsgi (:issue:`1178`)

19.4.4 / 2016/01/04
===================

- fix: check if a fileobject can be used with sendfile(2) (:issue:`1174`)
- doc: be more descriptive in errorlog option (:issue:`1173`)

19.4.3 / 2015/12/30
===================

- fix: don't check if a file is writable using os.stat with SELINUX (:issue:`1171`)

19.4.2 / 2015/12/29
===================

Core
++++

- improvement: handle HaltServer in manage_workers (:issue:`1095`)
- fix: Do not rely on sendfile sending requested count (:issue:`1155`)
- fix: claridy --no-sendfile default (:issue:`1156`)
- fix: LoggingCatch sendfile failure from no file descriptor (:issue:`1160`)

Logging
+++++++

- fix: Always send access log to syslog if syslog is on
- fix: check auth before trying to own a file (:issue:`1157`)


Documentation
+++++++++++++

- fix: Fix Slowloris broken link. (:issue:`1142`)
- Tweak markup in faq.rst

Testing
+++++++

- fix: gaiohttp test (:issue:`1164`)


19.4.1 / 2015/11/25
===================

- fix tornado worker (:issue:`1154`)

19.4.0 / 2015/11/20
===================

Core
++++

- fix: make sure that a user is able to access to the logs after dropping a
  privilege (:issue:`1116`)
- improvement: inherit the `Exception` class where it needs to be (:issue:`997`)
- fix: make sure headers are always encodedas latin1 RFC 2616 (:issue:`1102`)
- improvement: reduce arbiter noise (:issue:`1078`)
- fix: don't close the unix socket when the worker exit (:issue:`1088`)
- improvement: Make last logged worker count an explicit instance var (:issue:`1078`)
- improvement: prefix config file with its type (:issue:`836`)
- improvement: pidfile handing (:issue:`1042`)
- fix: catch OSError as well as ValueError on race condition (:issue:`1052`)
- improve support of ipv6 by backporting urlparse.urlsplit from Python 2.7 to
  Python 2.6.
- fix: raise InvalidRequestLine when the line contains maliscious data
  (:issue:`1023`)
- fix: fix argument to disable sendfile
- fix: add gthread to the list of supported workers (:issue:`1011`)
- improvement: retry socket binding up to five times upon EADDRNOTAVAIL
  (:issue:`1004`)
- **breaking change**: only honor headers that can be encoded in ascii to comply to
  the RFC 7230 (See :issue:`1151`).

Logging
+++++++

- add new parameters to access log (:issue:`1132`)
- fix: make sure that files handles are correctly reopenebd on HUP
  (:issue:`627`)
- include request URL in error message (:issue:`1071`)
- get username in access logs (:issue:`1069`)
- fix statsd logging support on Python 3 (:issue:`1010`)

Testing
+++++++

- use last version of mock.
- many fixes in Travis CI support
- miscellaneous improvements in tests

Thread worker
+++++++++++++

- fix: Fix self.nr usage in ThreadedWorker so that auto restart works as
  expected (:issue:`1031`)

Gevent worker
+++++++++++++

- fix quit signal handling (:issue:`1128`)
- add support for Python 3 (:issue:`1066`)
- fix: make graceful shutdown thread-safe (:issue:`1032`)

Tornado worker
++++++++++++++

- fix ssl options (:issue:`1146`, :issue:`1135`)
- don't check timeout when stopping gracefully (:issue:`1106`)

AIOHttp worker
++++++++++++++

- add SSL support (:issue:`1105`)

Documentation
+++++++++++++

- fix link to proc name setting (:issue:`1144`)
- fix worker class documentation (:issue:`1141`, :issue:`1104`)
- clarify graceful timeout documentation (:issue:`1137`)
- don't duplicate NGINX config files examples (:issue:`1050`, :issue:`1048`)
- add `web.py` framework example (:issue:`1117`)
- update Debian/Ubuntu installations instructions (:issue:`1112`)
- clarify `pythonpath` setting description (:issue:`1080`)
- tweak some example for python3
- clarify `sendfile` documentation
- miscellaneous typos in source code comments (thanks!)
- clarify why REMOTE_ADD may not be the user's IP address (:issue:`1037`)


Misc
++++

- fix: reloader should survive SyntaxError (:issue:`994`)
- fix: expose the reloader class to the worker.

History
=======

.. toctree::
   :titlesonly:

   2016-news
   2015-news
   2014-news
   2013-news
   2012-news
   2011-news
   2010-news
