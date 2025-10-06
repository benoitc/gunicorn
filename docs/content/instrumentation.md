<span id="instrumentation"></span>
# Instrumentation

!!! info "Added in 19.1"
    Gunicorn exposes optional instrumentation for the arbiter and workers using the
    statsD protocol over UDP. The `gunicorn.instrument.statsd` module turns
    Gunicorn into a statsD client.



UDP keeps Gunicorn isolated from slow statsD consumers, so metrics collection
does not impact request handling.

Tell Gunicorn where the statsD server is located:

```bash
gunicorn --statsd-host=localhost:8125 --statsd-prefix=service.app ...
```

The `Statsd` logger subclasses `gunicorn.glogging.Logger` and tracks:

- `gunicorn.requests` &mdash; request rate per second
- `gunicorn.request.duration` &mdash; request duration histogram (milliseconds.md)
- `gunicorn.workers` &mdash; number of workers managed by the arbiter (gauge.md)
- `gunicorn.log.critical` &mdash; rate of critical log messages
- `gunicorn.log.error` &mdash; rate of error log messages
- `gunicorn.log.warning` &mdash; rate of warning log messages
- `gunicorn.log.exception` &mdash; rate of exceptional log messages

See the [`statsd_host`](reference/settings.md#statsd_host) setting for additional options.

[statsD](https://github.com/etsy/statsd)
