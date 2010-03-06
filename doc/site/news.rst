template: doc.html
title: News

News
====

0.6.3 / 2010-03-07
------------------

* Make HTTP parsing faster.
* Some fixes (see `logs <http://github.com/benoitc/gunicorn/commits/master>`_)

0.6.2 / 2010-03-01
------------------

* Added support for chunked response.
* Added possibility to configure proc_name in config file.
* Improved HTTP parser. We now use buffers instead of strings to store temporary data.
* Improved performance in send.
* Workers are now murdered by age (the older is killed the first).


0.6.1 / 2010-02-24
------------------

* Added gunicorn config file support for django admin command
* Fix gunicorn config file. -c was broken.
* Removed TTIN/TTOU from workers which blocked other signals.

0.6 / 2010-02-22
------------------

* Added setproctitle
* Change privilege switch behaviour. We now works like NGINX, master keep the permission, new uid/gid permissions are only set to the workers.

0.5.1 / 2010-02-22
------------------

* Fix umask
* Added debian packaging

0.5 / 2010-02-20 
----------------

* Added `configuration file <configuration.html>`_ handler.
* Added support for pre/post fork hooks
* Added support for before_exec hook
* Added support for unix sockets
* Added launch of workers processes under different user/group
* Added umask option
* Added SCRIPT_NAME support
* Better support of some exotic settings for Django projects
* Better support of Paste-compatible applicatins
* Some refactoring to make the code easier to hack
* Allow multiple keys in request and response headers

