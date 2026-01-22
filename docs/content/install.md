# Installation

!!! note
    Gunicorn requires **Python 3.12 or newer**.

## Quick Install

=== "pip"

    ```bash
    pip install gunicorn
    ```

=== "pipx"

    ```bash
    pipx install gunicorn
    ```

=== "Docker"

    ```bash
    docker run -p 8000:8000 -v $(pwd):/app -w /app \
        python:3.12-slim sh -c "pip install gunicorn && gunicorn app:app"
    ```

    See the [Docker guide](guides/docker.md) for production configurations.

=== "System Packages"

    **Debian/Ubuntu:**
    ```bash
    sudo apt-get update
    sudo apt-get install gunicorn
    ```

    **Fedora:**
    ```bash
    sudo dnf install python3-gunicorn
    ```

    **Arch Linux:**
    ```bash
    sudo pacman -S gunicorn
    ```

    !!! warning
        System packages may lag behind the latest release. For production,
        prefer pip installation in a virtual environment.

## Virtual Environment (Recommended)

Always install Gunicorn inside a virtual environment to isolate dependencies:

```bash
# Create virtual environment
python -m venv venv

# Activate it
source venv/bin/activate  # Linux/macOS
# or: venv\Scripts\activate  # Windows

# Install gunicorn
pip install gunicorn
```

## From Source

Install the latest development version from GitHub:

```bash
pip install git+https://github.com/benoitc/gunicorn.git
```

Upgrade to the latest commit:

```bash
pip install -U git+https://github.com/benoitc/gunicorn.git
```

## Extra Packages

Gunicorn provides optional extras for additional worker types and features.
Install them with pip's bracket syntax:

```bash
pip install gunicorn[gevent,setproctitle]
```

### Worker Types

| Extra | Description |
|-------|-------------|
| `gunicorn[eventlet]` | Eventlet-based greenlet workers |
| `gunicorn[gevent]` | Gevent-based greenlet workers |
| `gunicorn[gthread]` | Threaded workers |
| `gunicorn[tornado]` | Tornado-based workers (not recommended) |

See the [design docs](design.md) for guidance on choosing worker types.

### Utilities

| Extra | Description |
|-------|-------------|
| `gunicorn[setproctitle]` | Set process name in `ps`/`top` output |

!!! tip
    If running multiple Gunicorn instances, use `setproctitle` with the
    [`proc_name`](reference/settings.md#proc_name) setting to distinguish them.

## Async Workers

For applications using async I/O patterns, install the appropriate greenlet
library:

=== "Gevent"

    ```bash
    pip install gunicorn[gevent]
    ```

    Run with:
    ```bash
    gunicorn app:app --worker-class gevent
    ```

=== "Eventlet"

    ```bash
    pip install gunicorn[eventlet]
    ```

    Run with:
    ```bash
    gunicorn app:app --worker-class eventlet
    ```

=== "ASGI (asyncio)"

    No extra installation required:

    ```bash
    gunicorn app:app --worker-class asgi
    ```

    For better performance, install uvloop:
    ```bash
    pip install uvloop
    gunicorn app:app --worker-class asgi --asgi-loop uvloop
    ```

!!! note
    Greenlet-based workers require the Python development headers. On Ubuntu:
    `sudo apt-get install python3-dev`

## Verify Installation

Check the installed version:

```bash
gunicorn --version
```

Test with a simple application:

```bash
echo 'def app(e, s): s("200 OK", []); return [b"OK"]' > test_app.py
gunicorn test_app:app
# Visit http://127.0.0.1:8000
```

## Next Steps

- [Quickstart](quickstart.md) - Get running in 5 minutes
- [Run](run.md) - CLI usage and framework integration
- [Configure](configure.md) - Configuration options
