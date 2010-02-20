template: doc.html
title: Configuration

This manual to setup Gunicorn in production and use the configuration file.


The configuration file
----------------------

`Gunicorn`_ 0.5 introduced the ability to read configuration from a file. Gunicorn will either look for "gunicorn.conf.py" in the current directory or a file referred through the -c flag.

See `github.com/benoitc/gunicorn/blob/master/examples/gunicorn.conf.py.sample <http://github.com/benoitc/gunicorn/blob/master/examples/gunicorn.conf.py.sample>`_ for an example of configuration file. 

Default configuration settings are:: 

  bind='127.0.0.1:8000',
  daemon=False,
  debug=False,
  logfile='-',
  loglevel='info',
  pidfile=None,
  workers=1,
  umask=0,
  user=None,
  group=None,

  after_fork=lambda server, worker: server.log.info(
                  "worker=%s spawned pid=%s" % (worker.id, str(worker.pid))),

  before_fork=lambda server, worker: server.log.info(
                  "worker=%s spawning" % worker.id),

  before_exec=lambda server: server.log.info("forked child, reexecuting")



after_fork:
  this function is called by the worker after forking. Arguments are the master and worker instances.
  
before_fork:
  this function is called by the worker before forking. Arguments are the master and worker instances.
  
before_exec:
  this function is called before relaunching the master. This happens when the master receive HUP or USR2 signals.
  
bind:
  address on which workers are listening. It could be a tcp address `IP:PORT` or  a unix address `unix:/path/to/sockfile`.

daemon:
  Start in daemonized mode.
  
debug:
  if set to `True`, only one worker will be launch and`the variable `wsgi.multiprocess` will be set to False.
  
group:
  the group on which workers processes will be launched.
  
logfile:
  path to the log file. `-` (stdout) by default.
  
loglevel:
  set debug level: info, debug, error
  
pidfile:
  file where master PID number will be saved
  
umask:
  in daemon mode, fix user mask of master.

user:
  the user on which workers processes will be launched.
  
Production setup
----------------

While some others HTTP proxies can be used we strongly advice you to use `NGINX <http://www/nginx.org>`_. If you choose another proxy server, make sure it can do buffering to handle slow clients.

An example config file for use with nginx is available at  `github.com/benoitc/gunicorn/blob/master/examples/nginx.conf <http://github.com/benoitc/gunicorn/blob/master/examples/nginx.conf>`_.
  

You may want to monitor `Gunicorn`_ service instead of launching it as daemon. You could for example use `runit <http://smarden.org/runit/>`_ for that purpose. An example config file for use with runit is available at  `github.com/benoitc/gunicorn/blob/master/examples/gunicorn_rc <http://github.com/benoitc/gunicorn/blob/master/examples/gunicorn_rc>`_. 

.. _Gunicorn: http://gunicorn.org