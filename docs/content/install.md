# Installation

!!! note
    Gunicorn requires **Python 3.12 or newer**.



```bash
pip install gunicorn
```

## From source

Install Gunicorn from GitHub if you want the latest development version:

```bash
pip install git+https://github.com/benoitc/gunicorn.git
```

Stay current by upgrading in place:

```bash
pip install -U git+https://github.com/benoitc/gunicorn.git
```

## Async workers

Install Eventlet or Gevent if your application benefits from cooperative I/O.
Both rely on `greenlet`, so make sure the Python headers are available (for
example, install the `python-dev` package on Ubuntu).

```bash
pip install greenlet            # Required for both
pip install eventlet            # For eventlet workers
pip install gunicorn[eventlet]  # Or, using extra
pip install gevent              # For gevent workers
pip install gunicorn[gevent]    # Or, using extra
```

!!! note
    Gevent also needs `libevent` 1.4.x or 2.0.4+. Install it from your package
    manager or build it manually if the packaged version is too old.



## Extra packages

Some Gunicorn options require additional dependencies. Install them via
extras to pull everything in with one command.

Most extras enable alternative worker types—see the
[design docs](design.md) for when each worker makes sense.

- `gunicorn[eventlet]` &mdash; Eventlet-based greenlet workers
- `gunicorn[gevent]` &mdash; Gevent-based greenlet workers
- `gunicorn[gthread]` &mdash; Threaded workers
- `gunicorn[tornado]` &mdash; Tornado-based workers (not recommended)

If you run more than one Gunicorn instance, the
[`proc_name`](reference/settings.md#proc_name) setting helps distinguish them in tools such
as `ps` and `top`.

- `gunicorn[setproctitle]` &mdash; Enables setting the process name

You can combine multiple extras, for example:

```bash
pip install gunicorn[gevent,setproctitle]
```

## Debian GNU/Linux

On Debian systems prefer the distribution packages unless you need per-project
virtual environments:

- Zero-effort installation: automatically starts multiple instances based on
  configs in `/etc/gunicorn.d`.
- Sensible log locations (`/var/log/gunicorn`) with `logrotate` support.
- Improved security: run each instance with a dedicated UNIX user/group.
- Safe upgrades: minimal downtime, reversible changes, and easy package purge.

### stable ("buster")

The Debian [stable](https://www.debian.org/releases/stable/) release ships
Gunicorn 19.9.0 (December 2020):

```bash
sudo apt-get install gunicorn3
```

Install Gunicorn 20.0.4 from [Debian Backports](https://backports.debian.org/)
by adding this line to `/etc/apt/sources.list`:

```text
deb http://ftp.debian.org/debian buster-backports main
```

Refresh package metadata and install:

```bash
sudo apt-get update
sudo apt-get -t buster-backports install gunicorn
```

### oldstable ("stretch")

Stretch provides Gunicorn 19.6.0 (December 2020). Install the Python 3 version:

```bash
sudo apt-get install gunicorn3
```

To upgrade to 19.7.1 from backports, add:

```text
deb http://ftp.debian.org/debian stretch-backports main
```

Then update and install:

```bash
sudo apt-get update
sudo apt-get -t stretch-backports install gunicorn3
```

### testing ("bullseye") and unstable ("sid")

Both distributions include Gunicorn 20.0.4. Install it in the usual way:

```bash
sudo apt-get install gunicorn
```

## Ubuntu

Ubuntu 20.04 LTS (Focal Fossa) and newer include Gunicorn 20.0.4. Keep it
current through the package manager:

```bash
sudo apt-get update
sudo apt-get install gunicorn
```
