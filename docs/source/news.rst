=========
Changelog
=========

20.1.0 - 2021-02-12
===================

- document WEB_CONCURRENCY is set by, at least, Heroku
- capture peername from accept: Avoid calls to getpeername by capturing the peer name returned by accept
- log a warning when a worker was terminated due to a signal
- fix tornado usage with latest versions of Django 
- add support for python -m gunicorn
- fix systemd socket activation example
- allows to set wsgi application in configg file using ``wsgi_app``
- document ``--timeout = 0``
- always close a connection when the number of requests exceeds the max requests
- Disable keepalive during graceful shutdown
- kill tasks in the gthread workers during upgrade
- fix latency in gevent worker when accepting new requests
- fix file watcher: handle errors when new worker reboot and ensure the list of files is kept
- document the default name and path of the configuration file
- document how variable impact configuration
- document the ``$PORT`` environment variable
- added milliseconds option to request_time in access_log
- added PIP requirements to be used for example
- remove version from the Server header
- fix sendfile: use ``socket.sendfile`` instead of ``os.sendfile``
- reloader: use  absolute path to prevent empty to prevent0 ``InotifyError`` when a file 
  is added to the working directory
- Add --print-config option to print the resolved settings at startup.
- remove the ``--log-dict-config`` CLI flag because it never had a working format
  (the ``logconfig_dict`` setting in configuration files continues to work)

** Breaking changes **

- minimum version is Python 3.5
- remove version from the Server header 

** Others **

- miscellaneous changes in the code base to be a better citizen with Python 3
- remove dead code
- fix documentation generation


History
=======

.. toctree::
   :titlesonly:

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

