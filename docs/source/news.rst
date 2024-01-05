=========
Changelog
=========

21.2.0 - 2023-07-19
===================

- fix thread worker: revert change considering connection as idle . 

*** NOTE ***

This is fixing the bad file description error.

21.1.0 - 2023-07-18
===================

- fix thread worker: fix socket removal from the queue

21.0.1 - 2023-07-17
===================

- fix documentation build

21.0.0 - 2023-07-17
===================

- support python 3.11
- fix gevent and eventlet workers
- fix threads support (gththread): improve performance and unblock requests
- SSL: now use SSLContext object
- HTTP parser: miscellaneous fixes
- remove unecessary setuid calls
- fix testing
- improve logging
- miscellaneous fixes to core engine

*** RELEASE NOTE ***

We made this release major to start our new release cycle. More info will be provided on our discussion forum.

History
=======

.. toctree::
   :titlesonly:

   2023-news
   2021-news
   2020-news
   2019-news
   2018-news
   2017-news
   2016-news
   2015-news
   2014-news
   2013-news
   2012-news
   2011-news
   2010-news

