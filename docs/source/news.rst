=========
Changelog
=========

22.0.0 - 2024-04-17
===================

- use `utime` to notify workers liveness 
- migrate setup to pyproject.toml
- fix numerous security vulnerabilities in HTTP parser (closing some request smuggling vectors)
- parsing additional requests is no longer attempted past unsupported request framing
- on HTTP versions < 1.1 support for chunked transfer is refused (only used in exploits)
- requests conflicting configured or passed SCRIPT_NAME now produce a verbose error
- Trailer fields are no longer inspected for headers indicating secure scheme
- support Python 3.12

** Breaking changes **

- minimum version is Python 3.7
- the limitations on valid characters in the HTTP method have been bounded to Internet Standards
- requests specifying unsupported transfer coding (order) are refused by default (rare)
- HTTP methods are no longer casefolded by default (IANA method registry contains none affected)
- HTTP methods containing the number sign (#) are no longer accepted by default (rare)
- HTTP versions < 1.0 or >= 2.0 are no longer accepted by default (rare, only HTTP/1.1 is supported)
- HTTP versions consisting of multiple digits or containing a prefix/suffix are no longer accepted
- HTTP header field names Gunicorn cannot safely map to variables are silently dropped, as in other software
- HTTP headers with empty field name are refused by default (no legitimate use cases, used in exploits)
- requests with both Transfer-Encoding and Content-Length are refused by default (such a message might indicate an attempt to perform request smuggling)
- empty transfer codings are no longer permitted (reportedly seen with really old & broken proxies)


** SECURITY **

- fix CVE-2024-1135

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
- SSL: noaw use SSLContext object
- HTTP parser: miscellaneous fixes
- remove unnecessary setuid calls
- fix testing
- improve logging
- miscellaneous fixes to core engine

*** RELEASE NOTE ***

We made this release major to start our new release cycle. More info will be provided on our discussion forum.

History
=======

.. toctree::
   :titlesonly:

   2024-news
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

