template: doc.html
title: Configuration

The Configuration File
----------------------

Gunciorn 0.5 introduced the ability to use a Python configuration file. Gunicorn will look for ``gunicorn.conf.py`` in the current working directory or what ever path is specified on the command line with the ``-c`` option.

A configuration file with default settings would look like this::

    bind = "127.0.0.1:8000" # Or "unix:/tmp/gunicorn.sock"
    daemon = False          # Whether work in the background
    debug = False           # Some extra logging
    logfile = "-"           # Name of the log file
    loglevel = "info"       # The level at which to log
    pidfile = None          # Path to a PID file
    workers = 1             # Number of workers to initialize
    umask = 0               # Umask to set when daemonizing
    user = None             # Change process owner to user
    group = None            # Change process group to group
    
    def after_fork(server, worker):
        fmt = "worker=%s spawned pid=%s"
        server.log.info(fmt % (worker.id, worker.pid))
    
    def before_fork(server, worker):
        fmt = "worker=%s spawning"
        server.log.info(fmt % worker.id)
    
    def before_exec(server):
        serer.log.info("Forked child, reexecuting.")

after_fork(server, worker):
    This is called by the worker after initialization. 
  
before_fork(server, worker):
    This is called by the worker just before forking.
  
before_exec(server):
    This function is called before relaunching the master. This happens when the master receives a HUP or USR2 signal.
  
bind:
    The address on which workers are listening. It can be a TCP address with a format of ``IP:PORT`` or a Unix socket address like ``unix:/path/to/socketfile``.

daemon:
    Whether or not to detach the server from the controlling terminal.
  
debug:
    If ``True``, only one worker will be launch and the variable ``wsgi.multiprocess`` will be set to False.
  
group:
    The group in which worker processes will be launched.
  
logfile:
    The path to the log file ``-`` (stdout) by default.
  
loglevel:
    The level at which to log. ``info``, ``debug``, or ``error`` for instance. Only log messages of equal or greater severity are logged.
  
pidfile:
    A file to store the master's PID.
  
umask:
    Used to set the umask when daemonizing.

user:
    The user as which worker processes will by launched.
  
Production setup
----------------

While some others HTTP proxies can be used we strongly advice you to use `NGINX <http://www/nginx.org>`_. If you choose another proxy server, make sure it can do buffering to handle slow clients.

An example config file for use with nginx is available at  `github.com/benoitc/gunicorn/blob/master/examples/nginx.conf <http://github.com/benoitc/gunicorn/blob/master/examples/nginx.conf>`_.
  

You may want to monitor `Gunicorn`_ service instead of launching it as daemon. You could for example use `runit <http://smarden.org/runit/>`_ for that purpose. An example config file for use with runit is available at  `github.com/benoitc/gunicorn/blob/master/examples/gunicorn_rc <http://github.com/benoitc/gunicorn/blob/master/examples/gunicorn_rc>`_. 

.. _Gunicorn: http://gunicorn.org