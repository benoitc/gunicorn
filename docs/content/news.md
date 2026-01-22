<span id="news"></span>
# Changelog

## 24.0.0 - 2026-XX-XX

### New Features

- **ASGI Worker (Beta)**: Native asyncio-based ASGI support for running async Python
  frameworks like FastAPI, Starlette, and Quart without external dependencies
  - HTTP/1.1 with keepalive connections
  - WebSocket support
  - Lifespan protocol for startup/shutdown hooks
  - Optional uvloop for improved performance

- **uWSGI Binary Protocol**: Support for receiving requests from nginx via
  `uwsgi_pass` directive

- **Documentation Migration**: Migrated to MkDocs with Material theme

### Breaking changes

- Minimum Python version is now 3.12

---

## 23.0.0 - 2024-08-10

- minor docs fixes ([PR #3217](https://github.com/benoitc/gunicorn/pull/3217), [PR #3089](https://github.com/benoitc/gunicorn/pull/3089), [PR #3167](https://github.com/benoitc/gunicorn/pull/3167))
- worker_class parameter accepts a class ([PR #3079](https://github.com/benoitc/gunicorn/pull/3079))
- fix deadlock if request terminated during chunked parsing ([PR #2688](https://github.com/benoitc/gunicorn/pull/2688))
- permit receiving Transfer-Encodings: compress, deflate, gzip ([PR #3261](https://github.com/benoitc/gunicorn/pull/3261))
- permit Transfer-Encoding headers specifying multiple encodings. note: no parameters, still ([PR #3261](https://github.com/benoitc/gunicorn/pull/3261))
- sdist generation now explicitly excludes sphinx build folder ([PR #3257](https://github.com/benoitc/gunicorn/pull/3257))
- decode bytes-typed status (as can be passed by gevent) as utf-8 instead of raising `TypeError` ([PR #2336](https://github.com/benoitc/gunicorn/pull/2336))
- raise correct Exception when encounting invalid chunked requests ([PR #3258](https://github.com/benoitc/gunicorn/pull/3258))
- the SCRIPT_NAME and PATH_INFO headers, when received from allowed forwarders, are no longer restricted for containing an underscore ([PR #3192](https://github.com/benoitc/gunicorn/pull/3192))
- include IPv6 loopback address ``[::1]`` in default for [forwarded-allow-ips](reference/settings.md#forwarded_allow_ips) and [proxy-allow-ips](reference/settings.md#proxy_allow_ips) ([PR #3192](https://github.com/benoitc/gunicorn/pull/3192))

!!! note
    - The SCRIPT_NAME change mitigates a regression that appeared first in the 22.0.0 release
    - Review your [forwarded-allow-ips](reference/settings.md#forwarded_allow_ips) setting if you are still not seeing the SCRIPT_NAME transmitted
    - Review your [forwarder-headers](reference/settings.md#forwarder_headers) setting if you are missing headers after upgrading from a version prior to 22.0.0


### Breaking changes

- refuse requests where the uri field is empty ([PR #3255](https://github.com/benoitc/gunicorn/pull/3255))
- refuse requests with invalid CR/LR/NUL in heade field values ([PR #3253](https://github.com/benoitc/gunicorn/pull/3253))
- remove temporary ``--tolerate-dangerous-framing`` switch from 22.0 ([PR #3260](https://github.com/benoitc/gunicorn/pull/3260))
- If any of the breaking changes affect you, be aware that now refused requests can post a security problem, especially so in setups involving request pipe-lining and/or proxies.

## 22.0.0 - 2024-04-17

- use `utime` to notify workers liveness 
- migrate setup to pyproject.toml
- fix numerous security vulnerabilities in HTTP parser (closing some request smuggling vectors)
- parsing additional requests is no longer attempted past unsupported request framing
- on HTTP versions < 1.1 support for chunked transfer is refused (only used in exploits)
- requests conflicting configured or passed SCRIPT_NAME now produce a verbose error
- Trailer fields are no longer inspected for headers indicating secure scheme
- support Python 3.12

### Breaking changes

- minimum version is Python 3.7
- the limitations on valid characters in the HTTP method have been bounded to Internet Standards
- requests specifying unsupported transfer coding (order.md) are refused by default (rare.md)
- HTTP methods are no longer casefolded by default (IANA method registry contains none affected)
- HTTP methods containing the number sign (#) are no longer accepted by default (rare.md)
- HTTP versions < 1.0 or >= 2.0 are no longer accepted by default (rare, only HTTP/1.1 is supported)
- HTTP versions consisting of multiple digits or containing a prefix/suffix are no longer accepted
- HTTP header field names Gunicorn cannot safely map to variables are silently dropped, as in other software
- HTTP headers with empty field name are refused by default (no legitimate use cases, used in exploits)
- requests with both Transfer-Encoding and Content-Length are refused by default (such a message might indicate an attempt to perform request smuggling)
- empty transfer codings are no longer permitted (reportedly seen with really old & broken proxies)


### Security

- fix CVE-2024-1135

## History

- [2026](2026-news.md)
- [2024](2024-news.md)
- [2023](2023-news.md)
- [2021](2021-news.md)
- [2020](2020-news.md)
- [2019](2019-news.md)
- [2018](2018-news.md)
- [2017](2017-news.md)
- [2016](2016-news.md)
- [2015](2015-news.md)
- [2014](2014-news.md)
- [2013](2013-news.md)
- [2012](2012-news.md)
- [2011](2011-news.md)
- [2010](2010-news.md)
