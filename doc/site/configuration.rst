template: doc.html
title: The Configuration File

The Configuration File
======================

Gunciorn 0.5 introduced the ability to use a Python configuration file. Gunicorn will look for ``gunicorn.conf.py`` in the current working directory or what ever path is specified on the command line with the ``-c`` option.

Example gunicorn.conf.py
------------------------
::

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
    proc_name = None        # Change the process name
    tmp_upload_dir = None   # Set path used to store temporary uploads
    
    after_fork=lambda server, worker: server.log.info(
            "Worker spawned (pid: %s)" % worker.pid),
        
    before_fork=lambda server, worker: True,

    before_exec=lambda server: server.log.info("Forked child, reexecuting"

Parameter Descriptions
----------------------

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
    
proc_name:
    If `setproctitle <http://pypi.python.org/pypi/setproctitle>`_ is installed, it allows you to set the process name for this Gunicorn instance.
  
umask:
    Used to set the umask when daemonizing.

user:
    The user as which worker processes will by launched.

tmp_upload_dir:
    Set the path used to store temporarily the body of the request.