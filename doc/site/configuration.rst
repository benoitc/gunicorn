template: doc.html
title: The Configuration File

The Configuration File
======================

Gunciorn 0.5 introduced the ability to use a Python configuration file. Gunicorn will look for ``gunicorn.conf.py`` in the current working directory or what ever path is specified on the command line with the ``-c`` option.

Example gunicorn.conf.py
------------------------
::

    arbiter = "egg:gunicorn"    # The arbiter to use for worker management
    backlog = 2048              # The listen queue size for the server socket
    bind = "127.0.0.1:8000"     # Or "unix:/tmp/gunicorn.sock"
    daemon = False              # Whether work in the background
    debug = False               # Some extra logging
    keepalive = 2               # Time we wait for next connection (in seconds)
    logfile = "-"               # Name of the log file
    loglevel = "info"           # The level at which to log
    pidfile = None              # Path to a PID file
    workers = 1                 # Number of workers to initialize
    umask = 0                   # Umask to set when daemonizing
    user = None                 # Change process owner to user
    group = None                # Change process group to group
    proc_name = None            # Change the process name
    tmp_upload_dir = None       # Set path used to store temporary uploads
    worker_connections=1000     # Maximum number of simultaneous connections
    
    after_fork=lambda server, worker: server.log.info(
            "Worker spawned (pid: %s)" % worker.pid)
        
    before_fork=lambda server, worker: True

    before_exec=lambda server: server.log.info("Forked child, reexecuting")

Parameter Descriptions
----------------------

after_fork(server, worker):
    This is called by the worker after initialization.
    
arbiter:
    The arbiter manages the worker processes that actually serve clients. It
    handles launching new workers and killing misbehaving workers among
    other things. By default the arbiter is `egg:gunicorn#main`. This arbiter
    only supports fast request handling requiring a buffering HTTP proxy.
    
    If your application requires the ability to handle prolonged requests to
    provide long polling, comet, or calling an external web service you'll
    need to use an async arbiter. Gunicorn has two async arbiters built in
    using `Eventlet`_ or `Gevent`_. You can also use the Evenlet arbiter with
    the `Twisted`_ helper.
    
backlog:
    The backlog parameter defines the maximum length for the queue of pending
    connections. The default is 2048. See listen(2) for more information
  
before_fork(server, worker):
    This is called by the worker just before forking.
  
before_exec(server):
    This function is called before relaunching the master. This happens when
    the master receives a HUP or USR2 signal.
  
bind:
    The address on which workers are listening. It can be a TCP address with a
    format of ``IP:PORT`` or a Unix socket address like
    ``unix:/path/to/socketfile``.

daemon:
    Whether or not to detach the server from the controlling terminal.
  
debug:
    If ``True``, only one worker will be launch and the variable
    ``wsgi.multiprocess`` will be set to False.
  
group:
    The group in which worker processes will be launched.
    
keepalive:
    KeepAlive timeout. The default is 2 seconds, which should be enough under
    most conditions for browsers to render the page and start retrieving extra
    elements for. Increasing this beyond 5 seconds is not recommended. Zero
    disables KeepAlive entirely.
  
logfile:
    The path to the log file ``-`` (stdout) by default.
  
loglevel:
    The level at which to log. ``info``, ``debug``, or ``error`` for instance.
    Only log messages of equal or greater severity are logged.
  
pidfile:
    A file to store the master's PID.
    
proc_name:
    A name for the master process. Only takes effect if setproctitle_ is
    installed. This alters the process names listed by commands like ``ps``.
    
umask:
    Used to set the umask when daemonizing.

user:
    The user as which worker processes will by launched.
    
worker_connections:
    Number of simultaneous connections a worker can handle when used with
    Eventlet or Gevent arbiter. The default is 1000.

tmp_upload_dir:
    Set the path used to store temporarily the body of the request.
    
.. _helper: http://bitbucket.org/which_linden/eventlet/src/tip/README.twisted
.. _Eventlet: http://eventlet.net
.. _Gevent: http://gevent.org
.. _Twisted: http://twistedmatrix.com
.. _setproctitle: http://pypi.python.org/pypi/setproctitle