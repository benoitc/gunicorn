# Running Gunicorn

You can run Gunicorn directly from the command line or integrate it with
popular frameworks like Django, Pyramid, or TurboGears. For deployment
patterns see the [deployment guide](deploy.md).

## Commands

After installation you have access to the `gunicorn` executable.

<span id="gunicorn-cmd"></span>
### `gunicorn`

Basic usage:

```bash
gunicorn [OPTIONS] [WSGI_APP]
```

`WSGI_APP` follows the pattern `MODULE_NAME:VARIABLE_NAME`. The module can be a
full dotted path. The variable refers to a WSGI callable defined in that
module.

!!! info "Changed in 20.1.0"
    `WSGI_APP` can be omitted when defined in a [configuration file](configure.md).



Example test application:

```python
def app(environ, start_response):
    """Simplest possible application object"""
    data = b"Hello, World!\n"
    status = "200 OK"
    response_headers = [
        ("Content-type", "text/plain"),
        ("Content-Length", str(len(data.md)))
    ]
    start_response(status, response_headers)
    return iter([data])
```

Run it with:

```bash
gunicorn --workers=2 test:app
```

You can also expose a factory function that returns the application:

```python
def create_app():
    app = FrameworkApp()
    ...
    return app
```

```bash
gunicorn --workers=2 'test:create_app()'
```

Passing positional and keyword arguments is supported but prefer
configuration files or environment variables for anything beyond quick tests.

#### Commonly used arguments

- `-c CONFIG`, `--config CONFIG` &mdash; configuration file (`PATH`, `file:PATH`, or
  `python:MODULE_NAME`).
- `-b BIND`, `--bind BIND` &mdash; socket to bind (host, host:port, `fd://FD`,
  or `unix:PATH`).
- `-w WORKERS`, `--workers WORKERS` &mdash; number of worker processes, typically
  two to four per CPU core. See the [FAQ](faq.md) for tuning tips.
- `-k WORKERCLASS`, `--worker-class WORKERCLASS` &mdash; worker type (`sync`,
  `gevent`, `tornado`, `gthread`). Read the
  [settings entry](reference/settings.md#worker_class) before switching classes.
- `-n APP_NAME`, `--name APP_NAME` &mdash; set the process name (requires
  [`setproctitle`](https://pypi.python.org/pypi/setproctitle)).

You can pass any setting via the environment variable
`GUNICORN_CMD_ARGS`. See the [configuration guide](configure.md) and
[settings reference](reference/settings.md) for details.

## Integration

Gunicorn integrates cleanly with Django and Paste Deploy applications.

### Django

Gunicorn looks for a WSGI callable named `application`. A typical invocation is:

```bash
gunicorn myproject.wsgi
```

!!! note
    Ensure your project is on `PYTHONPATH`. The easiest way is to run this command
    from the directory containing `manage.py`.



Set environment variables with `--env` and add your project to `PYTHONPATH`
if needed:

```bash
gunicorn --env DJANGO_SETTINGS_MODULE=myproject.settings myproject.wsgi
```

See [`raw_env`](reference/settings.md#raw_env) and [`pythonpath`](reference/settings.md#pythonpath) for
more options.

### Paste Deployment

Frameworks such as Pyramid and TurboGears often rely on Paste Deployment
configuration. You can use Gunicorn in two ways.

#### As a Paste server runner

Let your framework command (for example `pserve` or `gearbox`) load Gunicorn by
configuring it as the server:

```ini
[server:main]
use = egg:gunicorn#main
host = 127.0.0.1
port = 8080
workers = 3
```

This approach is quick to set up but Gunicorn cannot control how the
application loads. Options like [`reload`](reference/settings.md#reload) will be ignored and
hot upgrades are unavailable. Features such as daemon mode may conflict with
what your framework already provides. Prefer running those features through the
framework (for example `pserve --reload`). Advanced configuration is still
possible by pointing the `config` key at a Gunicorn configuration file.

#### Using Gunicorn's Paste support

Use the [`paste`](reference/settings.md#paste) option to load a Paste configuration directly
with the Gunicorn CLI. This unlocks Gunicorn's reloader and hot code upgrades,
while still letting Paste define the application object.

```bash
gunicorn --paste development.ini -b :8080 --chdir /path/to/project
```

Select a different application section by appending the name:

```bash
gunicorn --paste development.ini#admin -b :8080 --chdir /path/to/project
```

In both modes Gunicorn will honor any Paste `loggers` configuration unless you
override it with Gunicorn-specific [logging settings](reference/settings.md#logging).
