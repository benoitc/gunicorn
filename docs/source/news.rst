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
- Miscellaneous fixes and improvement for linting using Pylints


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
