<span id="signals"></span>
# Signal Handling

A quick reference to the signals handled by Gunicorn. This includes the signals
used internally to coordinate with worker processes.

## Master process

- `QUIT`, `INT` &mdash; quick shutdown.
- `TERM` &mdash; graceful shutdown; waits for workers to finish requests up to
  [`graceful_timeout`](reference/settings.md#graceful_timeout).
- `HUP` &mdash; reload configuration, spawn new workers, and gracefully stop old
  ones. If the app is not preloaded (see [`preload_app`](reference/settings.md#preload_app))
  the application code is reloaded too.
- `TTIN` &mdash; increase worker count by one.
- `TTOU` &mdash; decrease worker count by one.
- `USR1` &mdash; reopen log files.
- `USR2` &mdash; perform a binary upgrade. Send `TERM` to the old master afterwards
  to stop it. This also reloads preloaded applications (see
  [binary upgrades](#binary-upgrade)).
- `WINCH` &mdash; gracefully stop workers when Gunicorn runs as a daemon.

## Worker process

Workers rarely need direct signalling—if the master stays alive it will respawn
workers automatically.

- `QUIT`, `INT` &mdash; quick shutdown.
- `TERM` &mdash; graceful shutdown.
- `USR1` &mdash; reopen log files.

## Reload the configuration

Use `HUP` to reload Gunicorn on the fly:

```text
2013-06-29 06:26:55 [20682] [INFO] Handling signal: hup
2013-06-29 06:26:55 [20682] [INFO] Hang up: Master
2013-06-29 06:26:55 [20703] [INFO] Booting worker with pid: 20703
2013-06-29 06:26:55 [20702] [INFO] Booting worker with pid: 20702
2013-06-29 06:26:55 [20688] [INFO] Worker exiting (pid: 20688)
2013-06-29 06:26:55 [20687] [INFO] Worker exiting (pid: 20687)
2013-06-29 06:26:55 [20689] [INFO] Worker exiting (pid: 20689)
2013-06-29 06:26:55 [20704] [INFO] Booting worker with pid: 20704
```

Gunicorn reloads its settings, starts new workers, and gracefully shuts down the
previous ones. If the app is not preloaded it reloads the application module as
well.

<span id="binary-upgrade"></span>
## Upgrading to a new binary on the fly

!!! info "Changed in 19.6.0"
    PID files now follow the pattern `<name>.pid.2` instead of `<name>.pid.oldbin`.



You can replace the Gunicorn binary without downtime. Incoming requests remain
served and preloaded applications reload.

1. Replace the old binary and send `USR2` to the master. Gunicorn starts a new
   master whose PID file ends with `.2` and spawns new workers.

   ```text
   PID USER      PR  NI  VIRT  RES  SHR S  %CPU %MEM    TIME+  COMMAND
   20844 benoitc   20   0 54808  11m 3352 S   0.0  0.1   0:00.36 gunicorn: master [test:app]
   20849 benoitc   20   0 54808 9.9m 1500 S   0.0  0.1   0:00.02 gunicorn: worker [test:app]
   20850 benoitc   20   0 54808 9.9m 1500 S   0.0  0.1   0:00.01 gunicorn: worker [test:app]
   20851 benoitc   20   0 54808 9.9m 1500 S   0.0  0.1   0:00.01 gunicorn: worker [test:app]
   20854 benoitc   20   0 55748  12m 3348 S   0.0  0.2   0:00.35 gunicorn: master [test:app]
   20859 benoitc   20   0 55748  11m 1500 S   0.0  0.1   0:00.01 gunicorn: worker [test:app]
   20860 benoitc   20   0 55748  11m 1500 S   0.0  0.1   0:00.00 gunicorn: worker [test:app]
   20861 benoitc   20   0 55748  11m 1500 S   0.0  0.1   0:00.01 gunicorn: worker [test:app]
   ```

2. Send `WINCH` to the old master to gracefully stop its workers.

You can still roll back while the old master keeps its listen sockets:

1. Send `HUP` to the old master to restart its workers without reloading the
   config file.
2. Send `TERM` to the new master to shut down its workers gracefully.
3. Send `QUIT` to the new master to force it to exit.

If the new workers linger, send `KILL` after the new master quits.

To complete the upgrade, send `TERM` to the old master so only the new server
continues running:

```text
PID USER      PR  NI  VIRT  RES  SHR S  %CPU %MEM    TIME+  COMMAND
20854 benoitc   20   0 55748  12m 3348 S   0.0  0.2   0:00.45 gunicorn: master [test:app]
20859 benoitc   20   0 55748  11m 1500 S   0.0  0.1   0:00.02 gunicorn: worker [test:app]
20860 benoitc   20   0 55748  11m 1500 S   0.0  0.1   0:00.02 gunicorn: worker [test:app]
20861 benoitc   20   0 55748  11m 1500 S   0.0  0.1   0:00.01 gunicorn: worker [test:app]
```
