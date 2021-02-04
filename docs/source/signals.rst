.. _signals:

===============
Signal Handling
===============

A brief description of the signals handled by Gunicorn. We also document the
signals used internally by Gunicorn to communicate with the workers.

Master process
==============

- ``QUIT``, ``INT``: Quick shutdown
- ``TERM``: Graceful shutdown. Waits for workers to finish their
  current requests up to the :ref:`graceful-timeout`.
- ``HUP``: Reload the configuration, start the new worker processes with a new
  configuration and gracefully shutdown older workers. If the application is
  not preloaded (using the :ref:`preload-app` option), Gunicorn will also load
  the new version of it.
- ``TTIN``: Increment the number of processes by one
- ``TTOU``: Decrement the number of processes by one
- ``USR1``: Reopen the log files
- ``USR2``: Upgrade Gunicorn on the fly. A separate ``TERM`` signal should
  be used to kill the old master process. This signal can also be used to use
  the new versions of pre-loaded applications. See :ref:`binary-upgrade` for
  more information.
- ``WINCH``: Gracefully shutdown the worker processes when Gunicorn is
  daemonized.

Worker process
==============

Sending signals directly to the worker processes should not normally be
needed.  If the master process is running, any exited worker will be
automatically respawned.

- ``QUIT``, ``INT``: Quick shutdown
- ``TERM``: Graceful shutdown
- ``USR1``: Reopen the log files

Reload the configuration
========================

The ``HUP`` signal can be used to reload the Gunicorn configuration on the
fly.

::

    2013-06-29 06:26:55 [20682] [INFO] Handling signal: hup
    2013-06-29 06:26:55 [20682] [INFO] Hang up: Master
    2013-06-29 06:26:55 [20703] [INFO] Booting worker with pid: 20703
    2013-06-29 06:26:55 [20702] [INFO] Booting worker with pid: 20702
    2013-06-29 06:26:55 [20688] [INFO] Worker exiting (pid: 20688)
    2013-06-29 06:26:55 [20687] [INFO] Worker exiting (pid: 20687)
    2013-06-29 06:26:55 [20689] [INFO] Worker exiting (pid: 20689)
    2013-06-29 06:26:55 [20704] [INFO] Booting worker with pid: 20704


Sending a ``HUP`` signal will reload the configuration, start the new
worker processes with a new configuration and gracefully shutdown older
workers. If the application is not preloaded (using the :ref:`preload-app`
option), Gunicorn will also load the new version of it.

.. _binary-upgrade:

Upgrading to a new binary on the fly
====================================

.. versionchanged:: 19.6.0
   PID file naming format has been changed from ``<name>.pid.oldbin`` to
   ``<name>.pid.2``.

If you need to replace the Gunicorn binary with a new one (when
upgrading to a new version or adding/removing server modules), you can
do it without any service downtime - no incoming requests will be
lost. Preloaded applications will also be reloaded.

First, replace the old binary with a new one, then send a ``USR2`` signal to
the current master process. It executes a new binary whose PID file is
postfixed with ``.2`` (e.g. ``/var/run/gunicorn.pid.2``),
which in turn starts a new master process and new worker processes::

      PID USER      PR  NI  VIRT  RES  SHR S  %CPU %MEM    TIME+  COMMAND
    20844 benoitc   20   0 54808  11m 3352 S   0.0  0.1   0:00.36 gunicorn: master [test:app]
    20849 benoitc   20   0 54808 9.9m 1500 S   0.0  0.1   0:00.02 gunicorn: worker [test:app]
    20850 benoitc   20   0 54808 9.9m 1500 S   0.0  0.1   0:00.01 gunicorn: worker [test:app]
    20851 benoitc   20   0 54808 9.9m 1500 S   0.0  0.1   0:00.01 gunicorn: worker [test:app]
    20854 benoitc   20   0 55748  12m 3348 S   0.0  0.2   0:00.35 gunicorn: master [test:app]
    20859 benoitc   20   0 55748  11m 1500 S   0.0  0.1   0:00.01 gunicorn: worker [test:app]
    20860 benoitc   20   0 55748  11m 1500 S   0.0  0.1   0:00.00 gunicorn: worker [test:app]
    20861 benoitc   20   0 55748  11m 1500 S   0.0  0.1   0:00.01 gunicorn: worker [test:app]

At this point, two instances of Gunicorn are running, handling the
incoming requests together. To phase the old instance out, you have to
send a ``WINCH`` signal to the old master process, and its worker
processes will start to gracefully shut down.

At this point you can still revert to the old process since it hasn't closed
its listen sockets yet, by following these steps:

- Send a ``HUP`` signal to the old master process - it will start the worker
  processes without reloading a configuration file
- Send a ``TERM`` signal to the new master process to gracefully shut down its
  worker processes
- Send a ``QUIT`` signal to the new master process to force it quit

If for some reason the new worker processes do not quit, send a ``KILL`` signal
to them after the new master process quits, and everything will back to exactly
as before the upgrade attempt.

If the update is successful and you want to keep the new master process, send a
``TERM`` signal to the old master process to leave only the new server
running::

      PID USER      PR  NI  VIRT  RES  SHR S  %CPU %MEM    TIME+  COMMAND
    20854 benoitc   20   0 55748  12m 3348 S   0.0  0.2   0:00.45 gunicorn: master [test:app]
    20859 benoitc   20   0 55748  11m 1500 S   0.0  0.1   0:00.02 gunicorn: worker [test:app]
    20860 benoitc   20   0 55748  11m 1500 S   0.0  0.1   0:00.02 gunicorn: worker [test:app]
    20861 benoitc   20   0 55748  11m 1500 S   0.0  0.1   0:00.01 gunicorn: worker [test:app]
