=========
Changelog
=========


19.9.10 / 2019/11/23
====================

- unblock select loop during reload of a sync worker
- security fix: http desync attack
- handle `wsgi.input_terminated`
- added support for str and bytes in unix  socket addresses
- fixed `max_requests` setting
- headers values are now encoded as LATN1, not ASCII
- fixed `InotifyReloadeder`:  handle `module.__file__` is None
- fixed compatibility with tornado 6
- fixed root logging
- Prevent removalof unix sockets from `reuse_port`
- Clear tornado ioloop before os.fork
- Miscellaneous fixes and improvement for linting using Pylint

20.0 / 2019/10/30
=================

- Fixed `fdopen` `RuntimeWarning` in Python 3.8
- Added  check and exception for str type on value in Response process_headers method.
- Ensure WSGI header value is string before conducting regex search on it.
- Added pypy3 to list of tested environments
- Grouped `StopIteration` and `KeyboardInterrupt` exceptions with same body together in Arbiter.run()
- Added `setproctitle` module to `extras_require` in setup.py
- Avoid unnecessary chown of temporary files
- Logging: Handle auth type case insensitively
- Removed `util.import_module`
- Removed fallback for `types.SimpleNamespace` in tests utils
- Use `SourceFileLoader` instead instead of `execfile_`
- Use `importlib` instead of `__import__` and eval`
- Fixed eventlet patching
- Added optional `datadog <https://www.datadoghq.com>`_ tags for statsd metrics
- Header values now are encoded using latin-1, not ascii.
- Rewritten `parse_address` util added test
- Removed redundant super() arguments
- Simplify `futures` import in gthread module
- Fixed worker_connections` setting to also affects the Gthread worker type
- Fixed setting max_requests
- Bump minimum Eventlet and Gevent versions to 0.24 and 1.4
- Use Python default SSL cipher list by default
- handle `wsgi.input_terminated` extension
- Simplify Paste Deployment documentation
- Fix root logging: root and logger are same level.
- Fixed typo in ssl_version documentation
- Documented  systemd deployement unit examples
- Added systemd sd_notify support
- Fixed typo in gthread.py
- Added `tornado <https://www.tornadoweb.org/>`_ 5 and  6 support
- Declare our setuptools dependency
- Added support to `--bind` to open file descriptors
- Document how to serve WSGI app modules from Gunicorn
- Provide guidance on X-Forwarded-For access log in documentation
- Add support for named constants in the `--ssl-version` flag
- Clarify log format usage of header & environment in documentation
- Fixed systemd documentation to properly setup gunicorn unix socket
- Prevent removal unix socket for reuse_port
- Fix `ResourceWarning` when reading a Python config module
- Remove unnecessary call to dict keys method
- Support str and bytes for UNIX socket addresses
- fixed `InotifyReloadeder`:  handle `module.__file__` is None
- `/dev/shm` as a convenient alternative to making your own tmpfs mount in fchmod FAQ
- fix examples to work on python3
- Fix typo in `--max-requests` documentation
- Clear tornado ioloop before os.fork
- Miscellaneous fixes and improvement for linting using Pylint

Breaking Change
+++++++++++++++

- Removed gaiohttp worker
- Drop support for Python 2.x
- Drop support for EOL Python 3.2 and 3.3
- Drop support for Paste Deploy server blocks


History
=======

.. toctree::
   :titlesonly:

   2018-news
   2017-news
   2016-news
   2015-news
   2014-news
   2013-news
   2012-news
   2011-news
   2010-news
