template: doc.html
title: News

News
====

0.5.2 / 2010-02-22
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

