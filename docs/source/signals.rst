.. _signals:

================
Signals Handling
================

A brief description of the signals handled by Gunicorn. We also document the
signales used internally by Gunicorn to communicate with the workers. With the
exception of TTIN/TTOU the signals handling match the behaviour of `nginx
<http://wiki.nginx.org/CommandLine>`_.

Master process
==============

- **TERM**, **INT**: Quick shutdown
- **QUIT**: Graceful shutdwn. I waits for workers to finish their
  current request before finishing until the *graceful timeout*.
- **HUP**: Reload the configuration, start the new worker processes with a new
  configuration and gracefully shutdown older workers. If the application is
  not preloaded (using the ``--preload`` option), Gunicorn will also load the
  new version.
- **TTIN**: Increment the number of processes by one
- **TTOU**: Decrement the nunber of processes by one
- **USR1**: Reopen the log files
- **USR2**: Upgrade the Gunicorn on the fly. A separate **QUIT** signal should
  be used to kill the old process. This signal can also be used to use the new
  versions of pre-loaded applications.
- **WINCH**: Gracefully shutdown the worker processes when gunicorn is
  daemonized.

Worker process
==============

Sending signals directly to the worker processes should not normally be
needed.  If the master process is running, any exited worker will be
automatically respawned.

- **TERM**, **INT**: Quick shutdown
- **QUIT**: Graceful shutdown
- **USR1**: Reopen the log files
